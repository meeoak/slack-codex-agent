# Slack Codex Agent

Small Slack event server for a personal coding assistant.

## Environment variables

- `SLACK_BOT_TOKEN`: Slack bot token. Starts with `xoxb-`.
- `SLACK_SIGNING_SECRET`: Slack app signing secret from Basic Information.
- `OPENAI_API_KEY`: OpenAI API key.
- `OPENAI_MODEL`: Model name to use for replies.

## Slack Request URL

After deploying, use this URL in Slack Event Subscriptions:

```text
https://YOUR-RENDER-SERVICE.onrender.com/slack/events
```

## Slack bot events

Subscribe to:

- `app_mention`
- `message.im`
