import os
import aiohttp
from typing import List, Dict, Any, Optional

# Package Imports
from .base import BaseModel
from .types import CompletionResponse, LLMParams
from ..errors import MissingOpenAIAPIKeyException, InvalidLLMParamsException
from ..constants.messages import Messages
from ..processor.image import encode_image_to_base64
import ssl


class OpenAI(BaseModel):
    _instances: Dict[str, "OpenAI"] = {}
    _system_prompt = """
    Convert the following PDF page to markdown.
    Return only the markdown with no explanation text.
    Do not exclude any content from the page.
    """

    DEFAULT_LLM_PARAMS: LLMParams = {
        "max_tokens": 1000,
        "temperature": 0,
        "top_p": 1,
        "frequency_penalty": 0,
        "presence_penalty": 0,
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
    ):
        """Initializes the OpenAI model."""
        if api_key is None:
            api_key = self.get_api_key()

        super().__init__(api_key)

    @staticmethod
    def get_api_key(
        api_key: Optional[str] = None,
    ) -> str:
        """Gets the OpenAI API key from the environment variables incase it is not provided."""
        if api_key is None:
            api_key = os.getenv("OPENAI_API_KEY")
        if api_key is None:
            raise MissingOpenAIAPIKeyException()
        return api_key

    @staticmethod
    def validate_llm_params(params: Dict[str, Any]) -> LLMParams:
        """Validates and merges the provided LLM parameters with the default ones."""
        valid_keys = set(OpenAI.DEFAULT_LLM_PARAMS.keys())
        invalid_keys = set(params.keys()) - valid_keys
        if invalid_keys:
            raise InvalidLLMParamsException(
                f"Invalid LLM parameters: {', '.join(invalid_keys)}")

        return {**OpenAI.DEFAULT_LLM_PARAMS, **params}

    async def completion(
        self,
        image_path: str,
        maintain_format: bool,
        prior_page: str,
        model: str = "gpt-4o-mini",
        llm_params: Optional[Dict[str, Any]] = None,
    ) -> CompletionResponse:
        """OpenAI completion for image to markdown conversion.

        :param image_path: Path to the image file.
        :type image_path: str
        :param maintain_format: Whether to maintain the format from the previous page.
        :type maintain_format: bool
        :param prior_page: The markdown content of the previous page.
        :type prior_page: str
        :param model: The model to use for generating completions, defaults to "gpt-4o-mini"
        :type model: str, optional
        :return: The markdown content generated by the model.
        """
        messages = await self._prepare_messages(
            image_path=image_path,
            maintain_format=maintain_format,
            prior_page=prior_page,
        )

        validated_llm_params = self.validate_llm_params(llm_params or {})

        try:
            # response = await self._make_request(messages, model, validated_llm_params)
            response = await self._make_request(messages, model)
            return response
        except Exception as err:
            raise Exception(Messages.OPENAI_COMPLETION_ERROR.format(err))

    async def _make_request(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        # llm_params: LLMParams,
    ) -> CompletionResponse:
        """Makes a request to the OpenAI API for chat completions.

        :param messages: A list of messages in the conversation.
        :type messages: List[Dict[str, Any]]
        :param model: The model to use for generating completions.
        :type model: str
        :param temperature: Controls the randomness of the output, defaults to 0
        :type temperature: float, optional
        :raises Exception: If the response status code is not 200.
        :return: The response from the OpenAI API containing the completion content, input tokens, and output tokens.
        """

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                json={
                    "messages": messages,
                    "model": model,
                    # **llm_params,
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            ) as response:
                data = await response.json()

                if response.status != 200:
                    raise Exception(
                        Messages.OPENAI_NON_200_RESPONSE.format(
                            status_code=response.status, data=data
                        )
                    )

                return CompletionResponse(
                    content=data["choices"][0]["message"]["content"],
                    input_tokens=data["usage"]["prompt_tokens"],
                    output_tokens=data["usage"]["completion_tokens"],
                )

    async def _prepare_messages(
        self,
        image_path: str,
        maintain_format: bool,
        prior_page: str,
    ) -> List[Dict[str, Any]]:
        """Prepares the messages to send to the OpenAI API.

        :param image_path: Path to the image file.
        :type image_path: str
        :param maintain_format: Whether to maintain the format from the previous page.
        :type maintain_format: bool
        :param prior_page: The markdown content of the previous page.
        :type prior_page: str
        """
        # Default system message
        messages: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": self._system_prompt,
            },
        ]

        # If content has already been generated, add it to context.
        # This helps maintain the same format across pages.
        if maintain_format and prior_page:
            messages.append(
                {
                    "role": "system",
                    "content": f'Markdown must maintain consistent formatting with the following page: \n\n """{prior_page}"""',
                },
            )

        # Add Image to request
        base64_image = await encode_image_to_base64(image_path)
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64_image}"},
                    },
                ],
            }
        )

        return messages
