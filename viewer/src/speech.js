'use strict';
// 選択範囲の読み上げ（#430）。Windows標準の音声合成（System.Speech）を、PowerShellの子プロセスで動かす。
// 追加の同梱物が要らず、ライセンスと費用の方針に合う。画面側のspeechSynthesisは、Electronで声の一覧が空だったため使わない。

const { spawn: nodeSpawn } = require('node:child_process');

// 読み上げる文字の上限。数万文字の選択で、長時間止められない読み上げになるのを防ぐ（値は、実測してから見直す）。
const MAX_SPEECH_CHARS = 20000;

// 本文は標準入力（UTF-8）、声と速度は環境変数で渡す。スクリプトに埋め込むと、記号・引用符・改行で壊れるため。
// スクリプト自体は、-EncodedCommand（UTF-16LEのBase64）で渡し、コマンドラインの引用符の問題を避ける。
const SPEAK_SCRIPT = [
  '[Console]::InputEncoding = [System.Text.Encoding]::UTF8',
  '$text = [Console]::In.ReadToEnd()',
  'Add-Type -AssemblyName System.Speech',
  '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer',
  'if ($env:OBUNZU_SPEECH_VOICE) { try { $s.SelectVoice($env:OBUNZU_SPEECH_VOICE) } catch {} }',
  '$s.Rate = [int]$env:OBUNZU_SPEECH_RATE',
  '$s.Speak($text)',
].join('\n');

// 日本語の声だけを、名前の一覧で出す。声の名前は、環境によって違うため、実行時に取得する。
const LIST_VOICES_SCRIPT = [
  '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8',
  'Add-Type -AssemblyName System.Speech',
  '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer',
  '$s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like "ja*" } | ForEach-Object { $_.VoiceInfo.Name }',
].join('\n');

const encodeCommand = (script) => Buffer.from(script, 'utf16le').toString('base64');
const powershellArgs = (script) => ['-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encodeCommand(script)];

/** 速度（System.SpeechのRate）を、-10〜10の整数にそろえる。想定外は0（ふつう）。 */
function normalizeRate(rate) {
  const n = Number(rate);
  return Number.isInteger(n) && n >= -10 && n <= 10 ? n : 0;
}

/** 読み上げる文字を整える。空なら、null（読み上げない）。上限を超える分は、切り捨てる。 */
function prepareSpeechText(text) {
  if (typeof text !== 'string' || text.trim() === '') return null;
  return text.length > MAX_SPEECH_CHARS ? text.slice(0, MAX_SPEECH_CHARS) : text;
}

/**
 * 読み上げの管理。同時に読むのは、1つだけ（もう一度`speak`すると、前を止めてから始める）。
 * @param {{spawn?: Function, platform?: string, killTree?: (proc: object) => void}} [options] テストで差し替える
 */
function createSpeaker({ spawn = nodeSpawn, platform = process.platform, killTree = defaultKillTree } = {}) {
  let current = null;

  const supported = () => platform === 'win32';

  function stop() {
    const proc = current;
    current = null;
    if (proc) killTree(proc);
  }

  /** @returns {boolean} 読み上げを始めたか（非対応の環境・空の文字では、false） */
  function speak(text, { voice = '', rate = 0 } = {}) {
    const body = prepareSpeechText(text);
    if (!supported() || body === null) return false;
    stop();
    const proc = spawn('powershell.exe', powershellArgs(SPEAK_SCRIPT), {
      windowsHide: true,
      stdio: ['pipe', 'ignore', 'ignore'],
      env: { ...process.env, OBUNZU_SPEECH_VOICE: String(voice || ''), OBUNZU_SPEECH_RATE: String(normalizeRate(rate)) },
    });
    current = proc;
    const finished = () => { if (current === proc) current = null; };
    proc.on('exit', finished);
    proc.on('error', finished);   // powershell.exeが見つからない等。読み上げないだけで、アプリは止めない
    proc.stdin.on('error', () => {});   // 書き込み前に、停止で子プロセスが消えても、例外にしない
    proc.stdin.end(body, 'utf8');
    return true;
  }

  /** OSに入っている日本語の声の名前を、取得する。取得できなければ、空の配列。 */
  function listVoices() {
    if (!supported()) return Promise.resolve([]);
    return new Promise((resolve) => {
      let out = '';
      let proc;
      try {
        proc = spawn('powershell.exe', powershellArgs(LIST_VOICES_SCRIPT), { windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] });
      } catch {
        resolve([]);
        return;
      }
      proc.stdout.setEncoding('utf8');
      proc.stdout.on('data', (chunk) => { out += chunk; });
      proc.on('error', () => resolve([]));
      proc.on('close', () => resolve(out.split(/\r?\n/).map((s) => s.trim()).filter(Boolean)));
    });
  }

  return { speak, stop, listVoices, isSpeaking: () => current !== null, isSupported: supported };
}

// PowerShellの子プロセスごと止める。Windowsでは、単純なkillでは孫プロセスが残ることがあるため、taskkillを使う（worker-client.jsと同じ）。
function defaultKillTree(proc) {
  try {
    nodeSpawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
  } catch {
    try { proc.kill(); } catch { /* すでに終了している */ }
  }
}

module.exports = { createSpeaker, normalizeRate, prepareSpeechText, MAX_SPEECH_CHARS, SPEAK_SCRIPT };
