'use strict';
// 選択範囲の読み上げ（#430）。Windows標準の音声合成（System.Speech）を、PowerShellの子プロセスで動かす。
// 追加の同梱物が要らず、ライセンスと費用の方針に合う。画面側のspeechSynthesisは、Electronで声の一覧が空だったため使わない。

const { spawn: nodeSpawn, spawnSync } = require('node:child_process');

// 読み上げる文字の上限。数万文字の選択で、長時間止められない読み上げになるのを防ぐ（値は、実測してから見直す）。
const MAX_SPEECH_CHARS = 20000;

// 本文は標準入力の1行目（UTF-8のBase64。改行を含むため）、声と速度は環境変数で渡す。スクリプトに埋め込むと、記号・引用符・改行で
// 壊れるため。2行目以降は、操作（pause・resume）を受ける。標準入力が閉じられる（親が消える）か、stopが来たら、読み上げをやめて終わる。
// スクリプト自体は、-EncodedCommand（UTF-16LEのBase64）で渡し、コマンドラインの引用符の問題を避ける。
const SPEAK_SCRIPT = [
  '[Console]::InputEncoding = [System.Text.Encoding]::UTF8',
  '$text = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([Console]::In.ReadLine()))',
  'Add-Type -AssemblyName System.Speech',
  '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer',
  'if ($env:OBUNZU_SPEECH_VOICE) { try { $s.SelectVoice($env:OBUNZU_SPEECH_VOICE) } catch {} }',
  '$s.Rate = [int]$env:OBUNZU_SPEECH_RATE',
  '$null = $s.SpeakAsync($text)',
  '$line = [Console]::In.ReadLineAsync()',
  'while ($s.State -ne [System.Speech.Synthesis.SynthesizerState]::Ready) {',
  '  if ($line.IsCompleted) {',
  '    $cmd = $line.Result',
  '    if ($null -eq $cmd -or $cmd -eq "stop") { break }',
  '    if ($cmd -eq "pause") { $s.Pause() } elseif ($cmd -eq "resume") { $s.Resume() }',
  '    $line = [Console]::In.ReadLineAsync()',
  '  }',
  '  Start-Sleep -Milliseconds 40',
  '}',
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

/**
 * 使うPowerShellを選ぶ。PowerShell 7（pwsh.exe）が起動できれば、それを優先する。Windows PowerShell 5.1（powershell.exe）は、
 * 標準の声（Haruka Desktopなど）しか見えないが、7は、OneCoreの声（Haruka・Ayumi・Ichiro・Sayakaなど）も見える。
 * 7が入っていない環境では、5.1に戻す（全てのWindowsに入っている）。
 * Microsoft Store版の7は、実行エイリアスのため、ファイルの有無では判定できない。実際に起動して確かめる。
 * @returns {Promise<string>}
 */
function probePowerShell(spawn = nodeSpawn) {
  return new Promise((resolve) => {
    let proc;
    try {
      proc = spawn('pwsh.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', 'exit 0'], { windowsHide: true, stdio: 'ignore' });
    } catch {
      resolve('powershell.exe');
      return;
    }
    proc.on('error', () => resolve('powershell.exe'));
    proc.on('close', (code) => resolve(code === 0 ? 'pwsh.exe' : 'powershell.exe'));
  });
}

// 設定の速さの名前（5段階）と、System.SpeechのRate（-10〜10）の対応。
const SPEECH_RATES = Object.freeze({ slowest: -6, slow: -3, normal: 0, fast: 3, fastest: 6 });
const rateOf = (name) => SPEECH_RATES[name] ?? 0;

/** 使う声を決める。設定の声がOSにあればそれ、なければ（空・消えた声）日本語の声の先頭、声が無ければ空（OSの既定）。 */
function chooseVoice(wanted, voices) {
  if (typeof wanted === 'string' && wanted !== '' && voices.includes(wanted)) return wanted;
  return voices[0] ?? '';
}

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
 * @param {{spawn?: Function, platform?: string, killTree?: (proc: object) => void, killTreeSync?: (proc: object) => void, probeShell?: () => Promise<string>}} [options] テストで差し替える
 */
function createSpeaker({ spawn = nodeSpawn, platform = process.platform, killTree = defaultKillTree, killTreeSync = defaultKillTreeSync, probeShell = () => probePowerShell(spawn) } = {}) {
  const supported = () => platform === 'win32';
  let current = null;
  let paused = false;
  // 起動直後に、使うPowerShellを調べておく。調べ終わるまでは、5.1で動く（読み上げの開始を、待たせない）。
  let shell = 'powershell.exe';
  const shellReady = supported() ? Promise.resolve(probeShell()).then((file) => { shell = file; }, () => {}) : Promise.resolve();
  const shellFile = () => shell;

  /** @param {{wait?: boolean}} [options] `wait`: 止まるまで待つ。アプリの終了時に使う（待たないと、終了が先に進み、読み上げが残る）。 */
  function stop({ wait = false } = {}) {
    const proc = current;
    current = null;
    paused = false;
    if (proc) (wait ? killTreeSync : killTree)(proc);
  }

  /** @returns {boolean} 読み上げを始めたか（非対応の環境・空の文字では、false） */
  function speak(text, { voice = '', rate = 0 } = {}) {
    const body = prepareSpeechText(text);
    if (!supported() || body === null) return false;
    stop();
    const proc = spawn(shellFile(), powershellArgs(SPEAK_SCRIPT), {
      windowsHide: true,
      stdio: ['pipe', 'ignore', 'ignore'],
      env: { ...process.env, OBUNZU_SPEECH_VOICE: String(voice || ''), OBUNZU_SPEECH_RATE: String(normalizeRate(rate)) },
    });
    current = proc;
    const finished = () => { if (current === proc) { current = null; paused = false; } };
    proc.on('exit', finished);
    proc.on('error', finished);   // powershell.exeが見つからない等。読み上げないだけで、アプリは止めない
    proc.stdin.on('error', () => {});   // 書き込み前に、停止で子プロセスが消えても、例外にしない
    // 標準入力は、閉じない。続けて、pause・resumeの行を送るため（閉じるのは、プロセスが終わるとき）。
    proc.stdin.write(`${Buffer.from(body, 'utf8').toString('base64')}\n`);
    return true;
  }

  /** 一時停止する（読み上げ中だけ）。声の途中で止まる。 */
  function pause() {
    if (!current || paused) return false;
    paused = true;
    current.stdin.write('pause\n');
    return true;
  }

  /** 一時停止した所から、続ける。 */
  function resume() {
    if (!current || !paused) return false;
    paused = false;
    current.stdin.write('resume\n');
    return true;
  }

  /** OSに入っている日本語の声の名前を、取得する。取得できなければ、空の配列。 */
  function listVoices() {
    if (!supported()) return Promise.resolve([]);
    return shellReady.then(() => new Promise((resolve) => {
      let out = '';
      let proc;
      try {
        proc = spawn(shellFile(), powershellArgs(LIST_VOICES_SCRIPT), { windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] });
      } catch {
        resolve([]);
        return;
      }
      proc.stdout.setEncoding('utf8');
      proc.stdout.on('data', (chunk) => { out += chunk; });
      proc.on('error', () => resolve([]));
      proc.on('close', () => resolve(out.split(/\r?\n/).map((s) => s.trim()).filter(Boolean)));
    }));
  }

  return { speak, stop, pause, resume, listVoices, isSpeaking: () => current !== null, isPaused: () => paused, isSupported: supported };
}

// PowerShellの子プロセスごと止める。Windowsでは、単純なkillでは孫プロセスが残ることがあるため、taskkillを使う（worker-client.jsと同じ）。
function defaultKillTree(proc) {
  try {
    nodeSpawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
  } catch {
    try { proc.kill(); } catch { /* すでに終了している */ }
  }
}

// 終了時の停止。taskkillが終わるまで待つ。非同期だと、アプリの終了が先に進み、読み上げが残ることがある。
function defaultKillTreeSync(proc) {
  try {
    spawnSync('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore', timeout: 3000 });
  } catch {
    try { proc.kill(); } catch { /* すでに終了している */ }
  }
}

module.exports = { createSpeaker, probePowerShell, SPEECH_RATES, rateOf, chooseVoice, normalizeRate, prepareSpeechText, MAX_SPEECH_CHARS, SPEAK_SCRIPT };
