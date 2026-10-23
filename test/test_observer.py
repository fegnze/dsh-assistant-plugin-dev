"""Observations are optional callbacks, never a workspace service dependency."""
from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from observer import operation


class ObserverTest(unittest.TestCase):
    def setUp(self):
        self.guards = ExitStack()
        self.addCleanup(self.guards.close)
        for target in ('socket.create_connection', 'socket.socket.connect',
                       'urllib.request.urlopen', 'subprocess.run', 'subprocess.Popen'):
            self.guards.enter_context(patch(target, side_effect=AssertionError('external service used')))

    def test_default_preserves_waiting_state_without_workspace_access(self):
        result = operation(object(), 'test', 'fixture', lambda: {'status': 'waiting_registry'})
        self.assertEqual(result['status'], 'waiting_registry')
        self.assertTrue(result['observerRunId'])

    def test_callback_receives_bounded_lifecycle_with_one_run_identity(self):
        events = []
        result = operation(None, 'test', 'fixture', lambda: {'status': 'done'}, emit=events.append)
        self.assertEqual([event['event'] for event in events],
                         ['operation:start', 'step:start', 'step:end', 'operation:end'])
        self.assertEqual({event['runId'] for event in events}, {result['observerRunId']})
        self.assertEqual(events[0]['target'], 'fixture')
        self.assertEqual(events[-1]['status'], 'success')

    def test_error_propagates_without_leaking_details_to_callback(self):
        events = []
        error = ValueError('private failure detail')
        def fail():
            raise error
        with self.assertRaises(ValueError) as caught:
            operation(None, 'test', 'fixture', fail, emit=events.append)
        self.assertIs(caught.exception, error)
        self.assertEqual(events[-1]['status'], 'error')
        self.assertNotIn('private failure detail', str(events))

    def test_callback_failure_does_not_change_action_outcome(self):
        def unavailable(event):
            raise RuntimeError('observer unavailable')
        result = operation(None, 'test', 'fixture', lambda: {'status': 'waiting_registry'}, emit=unavailable)
        self.assertEqual(result['status'], 'waiting_registry')
        error = ValueError('action failed')
        def fail():
            raise error
        with self.assertRaises(ValueError) as caught:
            operation(None, 'test', 'fixture', fail, emit=unavailable)
        self.assertIs(caught.exception, error)


if __name__ == '__main__':
    unittest.main()
