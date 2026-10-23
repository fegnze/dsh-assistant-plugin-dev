// Development/test entry only; production Host uses ctx.subprocess.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const executable = process.env.DSH_ASSISTANT_PYTHON;
if (!executable) throw new Error('Set DSH_ASSISTANT_PYTHON to an explicit interpreter with requirements.txt installed');
const child = spawn(executable, ['-B', '-m', 'unittest', 'discover', '-s', 'test', '-v'], {
  cwd: fileURLToPath(new URL('../', import.meta.url)), stdio: 'inherit', shell: false,
});
child.once('error', error => { console.error(error.message); process.exitCode = 1; });
child.once('exit', (code, signal) => { process.exitCode = signal ? 1 : code ?? 1; });
