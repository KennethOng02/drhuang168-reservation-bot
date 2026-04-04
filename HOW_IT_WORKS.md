# How the Reservation Bot Works

A walkthrough of how the website was reverse-engineered and how the bot replicates what a browser does.

---

## Discovery: Reading the Website's HTML

Before writing any code, `curl` was used to inspect the raw HTML — exactly what a browser receives, but visible.

**The reservation page embeds an iframe:**

```html
<!-- /reservation/reservation.html -->
<iframe src="../dispensary/form.php" ...></iframe>
```

The schedule isn't on the main page at all. It lives at `/dispensary/form.php`. That's where all the action is.

---

## The Three Endpoints

| Step | Method | URL | Purpose |
|---|---|---|---|
| 1 | `GET` | `/dispensary/form.php` | Fetch the weekly schedule |
| 2 | `POST` | `/dispensary/reservation.php` | Select a slot |
| 3 | `POST` | `/dispensary/reservation-complete.php` | Submit patient details |

---

## Step 1 — Reading the Schedule (`form.php`)

Fetching `form.php` returns an HTML schedule. Available and full slots look different:

**Available slot** — has an `<a>` tag with class `reservetion-btn` and `data-*` attributes:

```html
<h2 class="infoName">呂岳聰</h2>
<a href="javascript:;"
   data-order="2026-04-6"
   data-id="3"
   data-csrf="5fca8c47..."
   data-token="105b8750..."
   class="reservetion-btn">
  <img src="button1.jpg" alt="掛號"/>
</a>
```

**Full slot** — no `<a>` tag, just the image directly:

```html
<h2 class="infoName">黃禎憲</h2>
<img src="button2.jpg" alt="掛號"/>
```

There is also a hidden form at the bottom of the page:

```html
<form id="reservationform" method="POST" action="reservation.php">
  <input type="hidden" name="datevalue"  value="" />
  <input type="hidden" name="value"      value="" />
  <input type="hidden" name="rostervalue" value="" />
  <input type="hidden" name="csrfvalue"  value="5fca8c47..." />
  <input type="hidden" name="tokenvalue" value="" />
</form>
```

**How the click works** — `jquery-action.js` reveals what happens when you click a slot button:

```javascript
$(".reservetion-btn").on("click", function() {
    $("#datevalue").val($(this).attr("data-order"));   // date
    $("#value").val($(this).attr("data-id"));          // slot ID
    $("#csrfvalue").val($(this).attr("data-csrf"));    // session token
    $("#tokenvalue").val($(this).attr("data-token"));  // slot token
    $("#reservationform").submit();                    // POST to reservation.php
})
```

The bot replicates this exact POST in Python — no browser needed.

---

## Step 2 — Selecting a Slot (`reservation.php`)

POST with the four values from the button's `data-*` attributes:

```
datevalue   = "2026-04-6"
value       = "3"              (slot ID)
rostervalue = "0"
csrfvalue   = "5fca8c47..."
tokenvalue  = "105b8750..."
```

The server responds with the patient details form HTML. The CSRF and token values are refreshed in this response and must be read back out for step 3:

```html
<form id="reservationform" method="post" action="reservation-complete.php">
  <input type="hidden" name="csrfvalue"   value="5fca8c47..." />
  <input type="hidden" name="tokenvalue"  value="105b8750..." />
  <input type="hidden" name="datevalue"   value="2026-04-6" />
  <input type="hidden" name="value"       value="3" />
  <input type="hidden" name="rostervalue" value="0" />
  ...patient fields...
</form>
```

---

## Step 3 — Submitting Patient Details (`reservation-complete.php`)

Final POST combining the hidden fields from step 2 with the patient's personal info:

```
csrfvalue      = "5fca8c47..."    ← from step 2 response
tokenvalue     = "105b8750..."    ← from step 2 response
datevalue      = "2026-04-6"
value          = "3"
rostervalue    = "0"
identitynumber = "A123456789"
username       = "王小明"
phonenumber    = "0912345678"
birthyears     = "1990"
birthmonth     = "1"
birthbay       = "1"             ← note: typo in the site's field name, "bay" not "day"
```

A successful response contains the confirmation page. An error response contains `201001` or `逾時` (timeout), which means the session expired and the whole flow must restart.

---

## Why `requests.Session()` Matters

The CSRF token is tied to a PHP session stored server-side. The server issues a `PHPSESSID` cookie on the first request and expects to see it on every subsequent request. Using `requests.Session()` carries that cookie automatically across all three steps — the server treats it as one continuous browser session. Without it, each request looks like a stranger and the tokens fail with error `201001`.

---

## Full Flow Diagram

```
GET /dispensary/form.php
  └─► HTML schedule page
        PHPSESSID cookie set
        Parse with BeautifulSoup:
          find <a class="reservetion-btn">
          read data-order, data-id, data-csrf, data-token
          read doctor name from sibling <h2 class="infoName">
                │
                ▼
POST /dispensary/reservation.php
  body: datevalue, value, rostervalue, csrfvalue, tokenvalue
  └─► HTML patient form
        Parse hidden fields (refreshed csrf + token)
                │
                ▼
POST /dispensary/reservation-complete.php
  body: hidden fields + identitynumber, username, phonenumber, birthyears, birthmonth, birthbay
  └─► Confirmation page ✓
        Save as confirmation_TIMESTAMP.html
        Open in browser
        macOS notification
```

---

## Key Insight

The website is plain HTML forms with no API, no app framework, and no bot protection. Once you can read HTML source, you can drive any form-based website from Python the same way a browser does — by sending the same HTTP requests with the same data.
