# Discord Voice

This app connects directly to the running Discord desktop client through Discord's local RPC IPC interface. It reads the selected voice channel and voice-state events, displays the current user and the three most recently speaking participants, and sends Discord RPC commands for mute, deafen, leave, and rejoin.

## Setup

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications) and copy its **Application ID**.
2. Open PYThing settings, find **Discord Voice**, and paste the ID into **Discord application ID**.
3. Keep the Discord desktop client running on the same computer as PYThing, then open the app.

Discord RPC is a local desktop-client interface; it does not use a bot token or a self-bot. The dashboard reports a connection error if Discord is not running, the application ID is missing/invalid, or the client does not expose its IPC endpoint. The app cannot control Discord while Discord is unavailable.
