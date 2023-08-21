Plugin for [Maubot](https://docs.mau.fi/maubot/index.html) to run meetings on
Matrix.

# Setup

Install the plugin into Maubot as normal, and associate it to a Matrix account

# Commands

- !startmeeting - Starts a meeting
- !endmeeting - Ends a meeting

During the meeting the bot will log *all* text messages to the internal plugin
DB. If a message contains "^info" or "^action" anywhere in the body, the bot
will add a reaction and store a tag.

When "!endmeeting" is called, the bot will emit 3 files - the "info" items, the
"action" items, and the full meeting log. Currently these are sent to the room
as TXT log files.

# Permissions

The bot checks permissions for who can start/end a meeting. The default is PL
50 (moderator), which is configurable.

# Config

The `backend_data` dict is used to store necessary config for a given backend.
Here is an example for the `ansible` backend (which posts to Discourse:

```
backend: ansible
backend_data:
    ansible:
        discourse_user: meetingbot
        discourse_key: redacted
        discourse_url: https://forum.ansible.com
        category_id: 15
```


