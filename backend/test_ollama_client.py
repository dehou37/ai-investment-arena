
from pydantic import BaseModel, Field

from app.services.llm.ollama_client import (
    OllamaClient,
    OllamaClientError,
)


class ConnectionTestResponse(BaseModel):
    message: str = Field(description="Connection test result")


def main():
    print("Testing Ollama client...")
    
    try:
        with OllamaClient() as client:
            result = client.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a test assistant. "
                            "Follow the requested response schema."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Set message to exactly: "
                            "Ollama client integration successful."
                        ),
                    },
                ],
                response_schema=ConnectionTestResponse,
            )

            parsed_result = ConnectionTestResponse.model_validate_json(
                result
            )

            print("\nSUCCESS: Ollama client is working.")
            print("Response:", parsed_result.message)

    except OllamaClientError as error:
        print("\nOLLAMA ERROR:", error)

    except Exception as error:
        print(
            f"\nUNEXPECTED ERROR: "
            f"{type(error).__name__}: {error}"
        )


if __name__ == "__main__":
    main()
