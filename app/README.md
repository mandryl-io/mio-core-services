# Mio WiFi setup app

A one-page phone UI for the pilot. There is no store build and no npm
install. The Pi serves this folder while the setup hotspot is up.

## On the phone

1. When Mio’s eyes fade slowly on and off, join the WiFi network
   **Mio-Setup**. The password is **miosetup**.
2. Open **http://10.42.0.1** (some phones offer a sign-in page that
   lands here by themselves).
3. Tap the home network, type its password, tap **Connect Mio**.

The setup WiFi disappears when Mio joins the home network. After that
the head, idle blink, and conversation start as usual.

## Files

`index.html` is the whole app. The Pi maps `/` to this file and talks
JSON at `/api/status`, `/api/networks`, and `/api/connect`.
