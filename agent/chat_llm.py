"""화면에서 전달한 대화 이력으로 일반 대화 응답을 생성한다."""

from openai import APIError, AsyncOpenAI


class ChatError(RuntimeError):
    """사용자에게 표시할 수 있는 일반 대화 오류."""


class OpenAIChatLLM:
    def __init__(self, model: str, client: AsyncOpenAI):
        self.model = model
        self.client = client

    async def reply(self, messages: list[dict[str, str]]) -> str:
        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=(
                    "한국어로 명확하고 친절하게 답하는 공지 도우미다. "
                    "현재 일반 대화만 가능하며 저장된 공지나 일정 DB를 검색할 수 없다. "
                    "공지 조회 요청에는 사이드바의 저장된 공지를 확인하도록 안내한다. "
                    "공지 등록은 이미지 첨부 후 추출 결과 카드의 저장 버튼으로 진행한다. "
                    "실제로 공지를 검색하거나 등록했다고 주장하지 않는다."
                ),
                input=messages,
                store=False,
            )
        except APIError as exc:
            # 외부 오류의 원문에는 요청 정보가 포함될 수 있어 반환하지 않는다.
            raise ChatError("대화 응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요.") from exc
        text = response.output_text.strip()
        if response.status != "completed" or not text:
            raise ChatError("대화 응답이 완성되지 않았습니다. 다시 시도해 주세요.")
        return text
