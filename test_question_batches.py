import json
import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from application_questions import build_question_graph, fill_question_page


def reply(data):
    return AIMessage(content=json.dumps(data))


def approvals(*keys):
    return reply({key: {"approved": True, "feedback": ""} for key in keys})


def request_data(call):
    return json.loads(next(message.content for message in call.args[0] if isinstance(message, HumanMessage)))


class QuestionBatchTest(unittest.TestCase):
    def setUp(self):
        context = patch("application_questions._applicant_context", return_value="Test applicant facts")
        context.start()
        self.addCleanup(context.stop)
        model = Mock()
        self.writer = model.bind_tools.return_value.bind.return_value
        self.critic = model.bind.return_value
        self.graph = build_question_graph(model)

    def test_independent_fields_share_one_writer_and_one_critic_call(self):
        fields = {"home.city": {"question": "City?"}, "work.city": {"question": "City?"}}
        self.writer.invoke.return_value = reply({"work.city": "Lakeview", "home.city": "Oakton"})
        self.critic.invoke.return_value = approvals("home.city", "work.city")
        result = self.graph.invoke({"company": "Example", "job_description": "Role details", "fields": fields})
        self.assertEqual(result, {"answers": {"home.city": "Oakton", "work.city": "Lakeview"}, "needs_input": {}})
        for agent in (self.writer, self.critic):
            agent.invoke.assert_called_once()
            request = request_data(agent.invoke.call_args)
            self.assertEqual(request["fields"], fields)
            self.assertEqual(request["job_description"], "Role details")

    def test_selective_retries_and_per_field_constraints(self):
        fields = {"bio": {"question": "Bio?"},
                  "roles": {"question": "Roles?", "allowed_options": ["Backend", "ML"], "allow_multiple": True},
                  "short": {"question": "One character?", "max_length": 1},
                  "why": {"question": "Why this role?"}}
        self.writer.invoke.side_effect = [
            reply({"bio": "Engineer", "roles": "ml\nbackend", "short": "😀", "why": "Generic"}),
            reply({"bio": "Unexpected rewrite", "short": "Too long", "why": "I work on retrieval"}),
            reply({"short": "x"}),
        ]
        self.critic.invoke.side_effect = [
            reply({"bio": {"approved": True, "feedback": ""}, "roles": {"approved": True, "feedback": ""},
                   "short": {"approved": True, "feedback": ""}, "why": {"approved": False, "feedback": "Be specific"}}),
            approvals("why", "short"), approvals("short"),
        ]
        result = self.graph.invoke({"fields": fields})
        self.assertEqual(result, {"answers": {"bio": "Engineer", "roles": "Backend\nML", "why": "I work on retrieval", "short": "x"},
                                  "needs_input": {}})
        for invoker in (self.writer, self.critic):
            self.assertEqual([list(request_data(call)["fields"]) for call in invoker.invoke.call_args_list],
                             [list(fields), ["short", "why"], ["short"]])
        second = request_data(self.writer.invoke.call_args_list[1])
        self.assertEqual(second["previous_drafts"], {"short": "😀", "why": "Generic"})
        self.assertEqual(second["feedback"]["why"], "Be specific")

    def test_missing_duplicate_and_unsupported_answers_stop_after_three_drafts(self):
        fields = {key: {"question": key} for key in ["good", "missing", "duplicate", "unsupported", "choice"]}
        fields["choice"]["allowed_options"] = ["Yes", "No"]
        self.writer.invoke.return_value = reply({"good": "OK", "missing": "unreviewed", "duplicate": "draft",
                                                "unsupported": "NEEDS_USER_INPUT", "choice": "maybe"})
        self.critic.invoke.return_value = AIMessage(content=(
            '{"good":{"approved":true,"feedback":""},"duplicate":{"approved":false},"duplicate":{"approved":true},'
            '"unsupported":{"approved":true,"feedback":""},"choice":{"approved":true,"feedback":""}}'
        ))
        result = self.graph.invoke({"fields": fields})
        self.assertEqual(result["answers"], {"good": "OK"})
        self.assertEqual(set(result["needs_input"]), set(fields) - {"good"})
        self.assertEqual(self.writer.invoke.call_count, 3)
        self.assertEqual(self.critic.invoke.call_count, 3)

    def test_history_lookup_and_fresh_invocations(self):
        self.writer.invoke.side_effect = [
            AIMessage(content="", tool_calls=[{"name": "applications_sql", "args": {"sql_query": "SELECT ?", "parameters": [1]}, "id": "lookup"}]),
            reply({"past": "Confirmed"}), reply({"new": "Different"}),
        ]
        self.critic.invoke.side_effect = [approvals("past"), approvals("new")]
        with patch("application_questions.read_applications", return_value={"rows": [1]}):
            self.assertEqual(self.graph.invoke({"fields": {"past": {"question": "Past answer?"}}})["answers"],
                             {"past": "Confirmed"})
        self.assertIn('"rows": [1]', request_data(self.critic.invoke.call_args)["history"][0])
        self.assertEqual(self.graph.invoke({"fields": {"new": {"question": "New question?"}}})["answers"],
                         {"new": "Different"})
        self.assertFalse(any(isinstance(m, ToolMessage) for m in self.writer.invoke.call_args.args[0]))
        self.assertEqual(self.graph.invoke({"fields": {}}), {"answers": {}, "needs_input": {}})

    def test_choice_reveals_a_new_batch_and_invalidates_stale_fields(self):
        visible = {
            "stale": {"question": "Full-time start?"},
            "role": {"question": "Role?", "allowed_options": ["Internship", "Full-time"]},
            "bio": {"question": "Bio?"},
            "date": {"question": "Earliest full-time start?"},
        }
        self.writer.invoke.side_effect = [
            reply({"role": "Internship", "stale": "May", "bio": "Engineer", "date": "May"}),
            reply({"date": "January", "duration": "Six months"}),
        ]
        self.critic.invoke.side_effect = [approvals(*visible), approvals("date", "duration")]
        fills = []

        def fill_field(key, answer):
            fills.append((key, answer))
            del visible[key]
            if key == "role":
                del visible["stale"]
                visible["date"] = {"question": "Earliest internship start?"}
                visible["duration"] = {"question": "How long?"}

        result = fill_question_page(self.graph, {"company": "Example"}, read_fields=lambda: visible.copy(),
                                    fill_field=fill_field)
        self.assertEqual(fills, [
            ("role", "Internship"), ("bio", "Engineer"), ("date", "January"), ("duration", "Six months"),
        ])
        self.assertEqual(result, {"answers": dict(fills), "needs_input": {}})
        self.assertEqual(list(request_data(self.writer.invoke.call_args)["fields"]), ["date", "duration"])

    def test_a_field_cleared_by_the_portal_is_reported(self):
        fields = {"about": {"question": "About you?"}}
        self.writer.invoke.return_value = reply({"about": "Engineer"})
        self.critic.invoke.return_value = approvals("about")
        fill = Mock()
        result = fill_question_page(self.graph, {}, read_fields=lambda: fields.copy(), fill_field=fill)
        fill.assert_called_once_with("about", "Engineer")
        self.assertEqual(result["answers"], {})
        self.assertIn("about", result["needs_input"])


if __name__ == "__main__":
    unittest.main()
