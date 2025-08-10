# core/openai_client.py
import os
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

# Create Azure OpenAI client
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

def chat_completion(messages, temperature=0.7, max_tokens=300):
    """
    Wrapper for Azure OpenAI Chat Completions (new SDK interface).
    """
    try:
        response = client.chat.completions.create(
            model=AZURE_DEPLOYMENT,  # Azure uses deployment name here
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Azure OpenAI API error: {e}")
        return None
