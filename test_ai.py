import requests

response = requests.post(
    "https://api.aimlapi.com/v1/chat/completions",
    headers={

        # Insert your AIML API Key instead of <YOUR_AIMLAPI_KEY>:
        "Authorization": "Bearer 3f0ddf0c6fd7482baaaed92ebf94cd8e",
        "Content-Type": "application/json"
    },
    json={
        "model": "mistralai/mistral-nemo",
        "messages": [
            {
                "role": "user",

                # Insert your question for the model here, instead of Hello:
                "content": "Hello"
            }
        ]
    }
)

data = response.json()
print(data)
