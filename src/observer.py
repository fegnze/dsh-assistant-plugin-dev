"""Optional bounded operation observations. No network, persistence, retries or scheduling."""
import uuid


class Observation:
    def __init__(self, name, title, steps, source='cli', target=None, emit=None):
        self.run_id = uuid.uuid4().hex
        self.emit = emit
        self.send('operation:start', operation=name, title=title, steps=steps, source=source, target=target)

    def send(self, event, **fields):
        if self.emit:
            try:
                self.emit({'event': event, 'runId': self.run_id, **fields})
            except Exception:
                pass  # Observation must not alter the operation outcome.

    def start(self, step):
        self.send('step:start', step=step)

    def end(self, step, status='success', error=None):
        self.send('step:end', step=step, status=status, error=error)

    def skip(self, step):
        self.end(step, 'skipped')

    def done(self, status, error=None):
        self.send('operation:end', status=status, error=error)


def operation(workspace, name, target, action, emit=None):
    # workspace remains a compatibility argument; never used to discover code or services.
    observation = Observation(name, name, [name], target=target, emit=emit)
    observation.start(name)
    try:
        result = action()
        observation.end(name)
        observation.done('success')
        return {**result, 'observerRunId': observation.run_id}
    except Exception:
        observation.end(name, 'error', 'Operation failed; inspect target state before retry')
        observation.done('error')
        raise
