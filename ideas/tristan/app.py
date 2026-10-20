import os

import uvicorn

# Entry point for `slack run`: the Slack CLI injects SLACK_BOT_TOKEN and SLACK_APP_TOKEN, the server starts the bot.
if __name__ == "__main__":
    uvicorn.run("whoknows.server:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8090")))
