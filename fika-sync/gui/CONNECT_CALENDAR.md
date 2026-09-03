# Connecting your calendar to Fika Sync

This guide is for **any team member**, not for whoever administers
the installation. If you're looking for how to configure Google or
Slack's Client ID/Secret (that's done once, for the whole app), that
part isn't here — talk to whoever administers your Fika Sync.

## Before you start: pick ONE path, not both

You can connect your calendar two different ways — **Google
Calendar** or **Cal.com** — but you have to pick **just one**, never
both at the same time for the same person.

Why? If your Cal.com is already connected to your Google Calendar
(very common: Cal.com usually writes your bookings there too), and
you also connect Google Calendar separately in Fika Sync, the **same
meeting would get counted twice** — your weekly hours would come out
inflated, double the real number. Fika Sync blocks this automatically
(if you try to connect the second path, it'll warn you), but it's
cleaner to pick the right one for your case from the start.

**Quick guide to choosing:**
- Do you use Cal.com for your bookings (even if your real calendar is
  in Outlook or elsewhere)? → Connect via **Cal.com**.
- Don't use Cal.com at all, and your calendar lives directly in
  Google? → Connect via **Google Calendar**.

## Option A — Connect via Google Calendar

1. Go to Fika Sync → **Team** tab.
2. Find your row (if it doesn't exist yet, ask the administrator to
   add you with "+ Add person", or add it yourself if you have
   access).
3. In your row's **"Google email"** field, type your Google email —
   the sync uses this to know whose calendar to look for, so don't
   leave it empty.
4. Tap **Save**.
5. Tap **"Connect my calendar"**.
6. The usual Google login screen opens — sign in with **your own
   account** (normal username and password, nothing technical).
7. Google will ask if you want to grant the app permission to read
   your calendar → tap **Allow**.
8. You're back on Fika Sync and your row now says "Calendar
   connected". Done.

**If Google rejects your login with an access-denied error:** your
email isn't added yet as a "test user" on the app's Google Cloud
project. Tell the administrator your exact email so they can add you
there — that's a step only they can do, not you.

## Option B — Connect via Cal.com

Unlike Google, there's no direct "sign in" button here — Cal.com
doesn't offer that automatic login on free accounts, so the path is
generating a key and pasting it yourself.

1. Go to Fika Sync → **Team** tab → find your row.
2. Tap **"Generate key ↗"** — it takes you to your Cal.com account
   (if you don't have one yet, you can sign up for free right there).
3. Inside Cal.com: **Settings → Developer → API Keys →
   Create new API key**.
4. **Copy the key as soon as it's generated** — Cal.com only shows it
   once; if you close that screen without copying it you'll have to
   generate a new one.
5. Go back to the Fika Sync tab (it stayed open in another browser
   tab) and paste the key into your row's **"Paste key (cal_...)"**
   field.
6. Tap **Connect**.
7. Your row now says "Cal.com connected". Done.

Your row's **"Cal.com username"** field is just a label so the team
can identify you more easily on screen — it doesn't need to be filled
in for the connection to work.

### If your real calendar is in Outlook (or elsewhere) and you use Cal.com as a bridge

Before connecting the key here, make sure Cal.com is already pulling
in your Outlook events: in your Cal.com account, go to
**Settings → Calendars → Office 365 / Outlook Calendar →
Connect**. Once that's working, the steps above (Option B) bring
those same events into Fika Sync without you having to touch anything
on the Google side.

## How to know it's connected correctly

Go back to the **Overview** tab. If your name shows up with hours
other than zero (or at zero but with a valid green/yellow/red color,
not the "demo" label in the top right), your connection is pulling in
real data.

## How to disconnect / switch paths

If you connected via one path and later want to switch to the other:

1. Go back to your row on Team.
2. Tap **Disconnect** on the path you had active.
3. Only then will the other path's button become available — while
   you have one connected, Fika Sync won't let you activate the
   second one (to avoid counting the same meeting twice, as explained
   above).

## Frequently asked questions

**Do I need the Google Client ID/Secret the administrator
configured?**
No. The app uses that behind the scenes, invisibly. You just use your
own normal Google login — you never see or touch any Client ID or
Secret.

**Can I use a Google account that isn't @gmail.com (for example,
linked to my Outlook email)?**
Yes, any Google Account works for Option A, whatever email it's
associated with. But careful: that gives you a new, empty Google
Calendar, it doesn't bring in your real Outlook events. If your real
calendar lives in Outlook, Option B (Cal.com) is the better fit.

**I connected and my hours look wrong (double, or zero).**
Let the administrator know — it could be a sync issue between Cal.com
and your real calendar, or your email in the Team row not exactly
matching the one you use to sign in.
