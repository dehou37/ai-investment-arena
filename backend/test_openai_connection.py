from openai import OpenAI
from openai import (
    AuthenticationError,
    APIConnectionError,
    APIStatusError,
    RateLimitError,
)

from app.core.config import settings


def test_openai_connection():
    if not settings.OPENAI_API_KEY:
        print("ERROR: OPENAI_API_KEY is not configured.")
        return

    print(f"Testing OpenAI API...")
    print(f"Configured model: {settings.OPENAI_MODEL}")

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        response = client.responses.create(
            model=settings.OPENAI_MODEL,
            input="Reply with exactly: OpenAI connection successful."
        )

        print("\nSUCCESS: OpenAI API connection established.")
        print(f"Model: {settings.OPENAI_MODEL}")
        print(f"Response: {response.output_text}")

    except AuthenticationError:
        print("ERROR: Authentication failed. Check your API key.")

    except RateLimitError as error:
        print(f"ERROR: Rate limit or quota issue: {error}")

    except APIConnectionError as error:
        print(f"ERROR: Could not connect to OpenAI: {error}")

    except APIStatusError as error:
        print(f"ERROR: OpenAI API returned HTTP {error.status_code}: {error}")

    except Exception as error:
        print(f"UNEXPECTED ERROR: {type(error).__name__}: {error}")


if __name__ == "__main__":
    test_openai_connection()