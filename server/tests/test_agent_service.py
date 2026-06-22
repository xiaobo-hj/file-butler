import json
import unittest
from unittest.mock import patch

from file_butler_server.services.agent import build_organization_plan


class AgentServiceTest(unittest.TestCase):
    def test_qwen_request_includes_existing_library_context(self):
        captured_payload = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "summary": "新合同",
                                            "folderPath": "家庭 / 合同",
                                            "newFileName": "新合同.pdf",
                                            "tags": ["合同"],
                                            "keyInfo": {},
                                            "reason": "参考现有合同目录",
                                            "confidence": 0.9,
                                        },
                                        ensure_ascii=False,
                                    )
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured_payload.update(json.loads(request.data.decode("utf-8")))
            return FakeResponse()

        with (
            patch.dict("os.environ", {"QWEN_API_KEY": "test-key"}, clear=False),
            patch("urllib.request.urlopen", fake_urlopen),
        ):
            plan = build_organization_plan(
                file_name="新合同.pdf",
                mime_type="application/pdf",
                text_preview="合同正文",
                library_context={
                    "folders": ["家庭 / 合同"],
                    "files": [
                        {
                            "fileName": "旧合同.pdf",
                            "folderPath": "家庭 / 合同",
                            "summary": "已经归档的旧合同",
                        }
                    ],
                },
            )

        user_content = json.loads(captured_payload["messages"][1]["content"])
        self.assertEqual(user_content["existingFolders"], ["家庭 / 合同"])
        self.assertEqual(user_content["existingFiles"][0]["fileName"], "旧合同.pdf")
        self.assertEqual(user_content["existingFiles"][0]["summary"], "已经归档的旧合同")
        self.assertEqual(plan.folder_path, "家庭 / 合同")


if __name__ == "__main__":
    unittest.main()
