"""Exercise the loop and cleanup locally without model or Modal credentials."""

from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from steps import s1_minimal as agent


def answer(content=None, calls=None):
    data = {"role": "assistant", "content": content, "reasoning_content": "private reasoning"}
    if calls:
        data["tool_calls"] = calls
    message = SimpleNamespace(content=content, tool_calls=calls, model_dump=lambda **_: data)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class AgentTests(unittest.TestCase):
    def test_tools_only_exec_in_sandbox(self):
        sandbox = Mock()
        process = sandbox.exec.return_value
        process.stdout.read.return_value = "ok"
        process.stderr.read.return_value = ""
        process.wait.return_value = 0
        for name, args in [("bash", {"command": "pwd"}), ("read_file", {"path": "a ' file"}),
                           ("write_file", {"path": "a ' file", "content": "hello '$x'"})]:
            self.assertEqual(agent.tool(sandbox, name, args), "exit=0\nok")
            self.assertEqual(sandbox.exec.call_args.kwargs, {"timeout": 60, "workdir": "/workspace"})
        self.assertEqual(sandbox.exec.call_args.args[-2:], ("a ' file", "hello '$x'"))
        with self.assertRaises(ValueError):
            agent.tool(sandbox, "unknown", {})

    def test_loop_tool_error_and_reasoning_roundtrip(self):
        client = Mock()
        call = SimpleNamespace(id="tool-1", function=SimpleNamespace(name="bash", arguments='{"command":"pwd"}'))
        client.chat.completions.create.side_effect = [answer(calls=[call]), answer("done")]
        with patch.object(agent, "tool", side_effect=ValueError("secret not logged")), redirect_stdout(StringIO()) as output:
            agent.run(client, "model", Mock(), "task")
        messages = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(messages[2]["reasoning_content"], "private reasoning")
        self.assertEqual(messages[3], {"role": "tool", "tool_call_id": "tool-1", "content": "tool error: ValueError"})
        self.assertIn("done", output.getvalue())
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("private reasoning", output.getvalue())

    def test_empty_answer_and_api_failure_propagate(self):
        client = Mock()
        for response in (answer(), answer(" ")):
            client.chat.completions.create.return_value = response
            with self.assertRaises(RuntimeError):
                agent.run(client, "model", Mock(), "task")
        client.chat.completions.create.side_effect = TimeoutError
        with self.assertRaises(TimeoutError):
            agent.run(client, "model", Mock(), "task")

    def test_existing_history_is_extended_without_replacing_it(self):
        history = [{"role": "system", "content": "existing"},
                   {"role": "user", "content": "remember apples"},
                   {"role": "assistant", "content": "apples"}]
        client = Mock()
        client.chat.completions.create.return_value = answer("apples")
        with redirect_stdout(StringIO()):
            result = agent.run(client, "model", Mock(), "What did I say?", messages=history)
        self.assertIs(result, history)
        self.assertEqual(len(history), 5)
        self.assertEqual(history[0], {"role": "system", "content": "existing"})
        self.assertEqual(history[-2], {"role": "user", "content": "What did I say?"})
        self.assertEqual(history[-1]["content"], "apples")

    def test_cleanup_on_failure(self):
        client, sandbox = Mock(), Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        with patch.object(agent.sys, "argv", ["agent", "task"]), \
             patch.object(agent, "client_and_model", return_value=(client, "model")), \
             patch.object(agent, "run", side_effect=RuntimeError), redirect_stdout(StringIO()):
            factory = Mock(return_value=sandbox)
            with self.assertRaisesRegex(SystemExit, "Failed: RuntimeError"):
                agent.main(create_sandbox=factory)
        factory.assert_called_once_with()
        sandbox.terminate.assert_called_once_with(wait=True)

    def test_custom_factory_success_and_failure(self):
        client, sandbox = Mock(), Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        with patch.object(agent.sys, "argv", ["agent", "task"]), \
             patch.object(agent, "client_and_model", return_value=(client, "model")), \
             patch.object(agent, "run") as run, redirect_stdout(StringIO()):
            factory = Mock(return_value=sandbox)
            agent.main(create_sandbox=factory)
            run.assert_called_once_with(client, "model", sandbox, "task")
            sandbox.terminate.assert_called_once_with(wait=True)
            with self.assertRaisesRegex(SystemExit, "^Failed: ValueError") as error:
                agent.main(create_sandbox=Mock(side_effect=ValueError("private config")))
            self.assertNotIn("private config", str(error.exception))


if __name__ == "__main__":
    unittest.main()
