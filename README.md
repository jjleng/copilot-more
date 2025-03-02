# MUST READ!!!

- Constantly hitting 429 (rate limit) can get your account banned.
- It seems you can hit 429 quicker with the Sonnet 3.7 models (probably smaller quotas).
- For RooCode users, highly advise to set **Rate limit** to at least 5s in Advanced Settings
- In copilot-more, use the MIN_DELAY_SECONDS and MAX_DELAY_SECONDS settings to help you from sending too many requests too quickly.

# copilot-more

`copilot-more` maximizes the value of your GitHub Copilot subscription by exposing models like Claude-3.7-Sonnet for use in agentic coding tools such as Cline, or any tool that supports bring-your-own-model setups. Unlike costly pay-as-you-go APIs, this approach lets you leverage these powerful models affordably.

The exposed models aren't limited to coding tasks—you can connect any AI client and customize parameters like temperature, context window length, and more.

## Ethical Use
- Respect the GitHub Copilot terms of service.
- Minimize the use of the models for non-coding purposes.
- Be mindful of the risk of being banned by GitHub Copilot for misuse.


## 🏃‍♂️ How to Run

1. Get the refresh token

   A refresh token is used to get the access token. This token should never be shared with anyone :). You can get the refresh token by following the steps below:

    - Run the following command and note down the returned `device_code` and `user_code`.:

    ```bash
    # 01ab8ac9400c4e429b23 is the client_id for the VS Code
    curl https://github.com/login/device/code -X POST -d 'client_id=01ab8ac9400c4e429b23&scope=user:email'
    ```

    - Open https://github.com/login/device/ and enter the `user_code`.

    - Replace `YOUR_DEVICE_CODE` with the `device_code` obtained earlier and run:

    ```bash
    curl https://github.com/login/oauth/access_token -X POST -d 'client_id=01ab8ac9400c4e429b23&scope=user:email&device_code=YOUR_DEVICE_CODE&grant_type=urn:ietf:params:oauth:grant-type:device_code'
    ```

    - Note down the `access_token` starting with `gho_`.


2. Install and run copilot_more

  * Bare metal installation:

    ```bash
    git clone https://github.com/jjleng/copilot-more.git
    cd copilot-more
    # install dependencies
    poetry install
    # run the server. Replace gho_xxxxx with the refresh token you got in the previous step. Note, you can use any port number you want.
    REFRESH_TOKEN=gho_xxxxx poetry run uvicorn copilot_more.server:app --port 15432
    ```
  * Docker Compose installation:

    ```bash
    git clone https://github.com/jjleng/copilot-more.git
    cd copilot-more
    # run the server. Ensure you either have the refresh token in the .env file or pass it as an environment variable.
    docker-compose up --build
    ```

3. Alternatively, use the `refresh-token.sh` script to automate the above.

## ⚙️ Configuration

The application allows you to customize behavior through environment variables or a `.env` file. Available configuration options:

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| GitHub Refresh Token | `REFRESH_TOKEN` | None (Required) | GitHub Copilot refresh token |
| Editor Version | `EDITOR_VERSION` | vscode/1.97.2 | Editor version for API requests |
| Max Tokens | `MAX_TOKENS` | 10240 | Maximum tokens in responses |
| Timeout | `TIMEOUT_SECONDS` | 300 | API request timeout in seconds |
| Record Traffic | `RECORD_TRAFFIC` | false | Whether to record API traffic |
| Min Delay | `MIN_DELAY_SECONDS` | 0.0 | Minimum random delay before requests (0.0 = no delay) |
| Max Delay | `MAX_DELAY_SECONDS` | 0.0 | Maximum random delay before requests (0.0 = no delay) |

You can control request throttling by setting both `MIN_DELAY_SECONDS` and `MAX_DELAY_SECONDS`. For example, to add a random delay between 5 and 15 seconds before each request:

```bash
MIN_DELAY_SECONDS=5 MAX_DELAY_SECONDS=15 poetry run uvicorn copilot_more.server:app --port 15432
```

Or in your `.env` file:
```
MIN_DELAY_SECONDS=5
MAX_DELAY_SECONDS=15
```

See `.env.example` for a template configuration file. You can `cp .env.example .env` and modify the values as needed.

Once you have set up your `.env` file with all your configuration settings, you can simply run the server without specifying environment variables on the command line:

```bash
poetry run uvicorn copilot_more.server:app --port 15432
```

## ✨ Magic Time
Now you can connect Cline or any other AI client to `http://localhost:15432` and start coding with the power of GPT-4o and Claude-3.5-Sonnet without worrying about the cost. Note, the copilot-more manages the access token, you can use whatever string as API keys if Cline or the AI tools ask for one.

### 🚀 Cline Integration

1. Install Cline `code --install-extension saoudrizwan.claude-dev`
2. Open Cline and go to the settings
3. Set the following:
     * **API Provider**: `OpenAI Compatible`
     * **API URL**: `http://localhost:15432`
     * **API Key**: `anything`
     * **Model**: `gpt-4o`, `claude-3.7-sonnet`, `o1`, `o3-mini`


## 🔍 Debugging

For troubleshooting integration issues, you can enable traffic logging to inspect the API requests and responses.

### Traffic Logging

To enable logging, set the `RECORD_TRAFFIC` environment variable to `true`:

```bash
RECORD_TRAFFIC=true REFRESH_TOKEN=gho_xxxx poetry run uvicorn copilot_more.server:app --port 15432
```

Alternatively, you can add `RECORD_TRAFFIC=true` to your `.env` file.

All traffic will be logged to files in the current directory with the naming pattern: copilot_traffic_YYYYMMDD_HHMMSS.mitm

Attach this file when reporting issues. Please zip the original file that ends with the '.mitm' extension and upload to the GH issues.

Note: the Authorization header has been redacted, so the refresh token won't be leaked.

## 🤔 Limitation

The GH Copilot models sit behind an API server that is not fully compatible with the OpenAI API. You cannot pass in a message like this:

```json
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "<task>\nreview the code\n</task>"
        },
        {
          "type": "text",
          "text": "<task>\nreview the code carefully\n</task>"
        }
      ]
    }
```
copilot-more takes care of this limitation by converting the message to a format that the GH Copilot API understands. However, without the `type`, we cannot leverage the models' vision capabilities, so that you cannot do screenshot analysis.
