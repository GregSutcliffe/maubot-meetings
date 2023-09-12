Plugin for [Maubot](https://docs.mau.fi/maubot/index.html) to run meetings on
Matrix.

# Setup

Install the plugin into Maubot as normal, and associate it to a Matrix account

# Commands

- !startmeeting - Starts a meeting
- !endmeeting - Ends a meeting

During the meeting the bot will log *all* text messages to the internal plugin
DB. It will also look for things starting "^" and perform an action if found.
The following in-line commands are supported:

- ^meetingname - set the meetingname (responds with a notice)
- ^topic - set the topic (no reaction for this at present)
- ^info - log an Info item (and add a reaction)
- ^action - log an Action item (and add a reaction)

When "!endmeeting" is called, the bot will pass the control to the backend
plugin (currently either `ansible` or `fedora`). This will determine what is
done with the logs:

- Ansible posts the logs to https://forum.ansible.com
- Fedora posts the logs aas files to the Matrix room (Mote support in progress)

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

# Optional dependencies

Maubot has no way to force extra dependencies, so we list them here:

- Ansible backend: none
- Fedora backend:
  - slugify


