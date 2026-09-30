# OpenAI Decisions API status

Checked 2026-09-30. OpenAI's [DevDay recap](https://openai.com/index/devday-2026-recap/) announces a Decisions API that focuses Luna on user-defined questions with finite predefined answers. It accepts text or image context. The announcement says limited preview is available and a broader release is planned in the coming days.

The public announcement does not specify an HTTP endpoint, model identifier, request/response schema, confidence semantics, billing contract or account-access procedure. Searches of the official developer documentation during this check did not establish those details. This is a documented pending integration, not a working adapter.

Do not substitute Chat Completions or Responses and label it native Decisions support. An `openai-decisions` configuration remains explicitly unsupported until its published contract or authorized preview documentation is available. The existing adapter registry can add it without changing task definitions.

Before enabling dispatch, verify the official contract, preserve exact input and question/choice bytes, validate returned probabilities and identity, bind conservative spending bounds, and cover invalid, partial and uncertain outcomes plus no-replay recovery offline. Live verification then requires its own explicit task/request/budget scope and authorized credential. The previous OpenRouter smoke approval does not cover it.
