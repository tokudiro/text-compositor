'use strict';
// 選択範囲の読み上げ（#430）。PowerShellを起動せず、子プロセスを差し替えて、渡し方と止め方を確認する。

const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const { test } = require('node:test');

const { createSpeaker, normalizeRate, prepareSpeechText, MAX_SPEECH_CHARS } = require('../src/speech');

function fakeProcess(pid) {
  const proc = new EventEmitter();
  proc.pid = pid;
  proc.stdin = new PassThrough();
  proc.stdout = new PassThrough();
  proc.stdinChunks = [];
  proc.stdin.on('data', (c) => proc.stdinChunks.push(c));
  return proc;
}

function setup(platform = 'win32') {
  const spawned = [];
  const killed = [];
  const speaker = createSpeaker({
    platform,
    spawn: (file, args, options) => { const proc = fakeProcess(100 + spawned.length); spawned.push({ file, args, options, proc }); return proc; },
    killTree: (proc) => killed.push(proc.pid),
  });
  return { speaker, spawned, killed };
}

test('the text goes through stdin as UTF-8, not on the command line', () => {
  const { speaker, spawned } = setup();
  const text = 'こんにちは "引用符" `記号` $x\n改行';
  assert.equal(speaker.speak(text), true);
  const [{ file, args, options, proc }] = spawned;
  assert.equal(file, 'powershell.exe');
  assert.equal(Buffer.concat(proc.stdinChunks).toString('utf8'), text);
  assert.equal(args.join(' ').includes('こんにちは'), false);
  assert.equal(options.windowsHide, true);
});

test('voice and rate go through environment variables', () => {
  const { speaker, spawned } = setup();
  speaker.speak('x', { voice: 'Microsoft Haruka', rate: -3 });
  const { env } = spawned[0].options;
  assert.equal(env.OBUNZU_SPEECH_VOICE, 'Microsoft Haruka');
  assert.equal(env.OBUNZU_SPEECH_RATE, '-3');
});

test('an invalid rate falls back to 0', () => {
  for (const bad of [11, -11, 1.5, 'fast', undefined, NaN]) assert.equal(normalizeRate(bad), 0, String(bad));
  assert.equal(normalizeRate(10), 10);
  assert.equal(normalizeRate(-10), -10);
});

test('empty text is not spoken and starts no process', () => {
  const { speaker, spawned } = setup();
  for (const text of ['', '  \n', undefined, null, 42]) assert.equal(speaker.speak(text), false, String(text));
  assert.equal(spawned.length, 0);
});

test('long text is cut at the limit', () => {
  assert.equal(prepareSpeechText('a'.repeat(MAX_SPEECH_CHARS + 5)).length, MAX_SPEECH_CHARS);
});

test('speaking again stops the previous one first', () => {
  const { speaker, spawned, killed } = setup();
  speaker.speak('1');
  speaker.speak('2');
  assert.deepEqual(killed, [spawned[0].proc.pid]);
  assert.equal(spawned.length, 2);
  assert.equal(speaker.isSpeaking(), true);
});

test('stop kills the process and clears the state; stopping when idle is harmless', () => {
  const { speaker, spawned, killed } = setup();
  speaker.stop();
  assert.deepEqual(killed, []);
  speaker.speak('x');
  speaker.stop();
  assert.deepEqual(killed, [spawned[0].proc.pid]);
  assert.equal(speaker.isSpeaking(), false);
});

test('the state clears when the speech ends or the process fails to start', () => {
  const { speaker, spawned } = setup();
  speaker.speak('x');
  spawned[0].proc.emit('exit', 0);
  assert.equal(speaker.isSpeaking(), false);
  speaker.speak('y');
  spawned[1].proc.emit('error', new Error('ENOENT'));
  assert.equal(speaker.isSpeaking(), false);
});

test('a late exit of an old process does not clear the new speech', () => {
  const { speaker, spawned } = setup();
  speaker.speak('1');
  speaker.speak('2');
  spawned[0].proc.emit('exit', 1);
  assert.equal(speaker.isSpeaking(), true);
});

test('on other platforms, nothing is spoken and no voices are listed', async () => {
  const { speaker, spawned } = setup('linux');
  assert.equal(speaker.isSupported(), false);
  assert.equal(speaker.speak('x'), false);
  assert.deepEqual(await speaker.listVoices(), []);
  assert.equal(spawned.length, 0);
});

test('listVoices returns the trimmed names, one per line', async () => {
  const { speaker, spawned } = setup();
  const promise = speaker.listVoices();
  const { proc } = spawned[0];
  proc.stdout.write('Microsoft Haruka\r\nMicrosoft Ayumi \r\n\r\n');
  proc.emit('close', 0);
  assert.deepEqual(await promise, ['Microsoft Haruka', 'Microsoft Ayumi']);
});

test('listVoices returns an empty list when PowerShell cannot start', async () => {
  const { speaker, spawned } = setup();
  const promise = speaker.listVoices();
  spawned[0].proc.emit('error', new Error('ENOENT'));
  assert.deepEqual(await promise, []);
});
