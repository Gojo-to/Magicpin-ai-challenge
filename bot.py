import json
import re
from pathlib import Path

# Project and dataset locations
BASE_DIR = Path(__file__).resolve().parent
DATASET = BASE_DIR / "dataset"


def load_folder(folder):
    """Load JSON records from dataset/<folder>, indexed by their IDs."""
    data = {}
    folder_path = DATASET / folder

    if not folder_path.exists():
        print(f"Folder not found: {folder_path}")
        return data

    id_fields = {
        "categories": ("slug", "id"),
        "merchants": ("merchant_id", "id"),
        "customers": ("customer_id", "id"),
        "triggers": ("id", "trigger_id"),
    }.get(folder, ("id",))

    def add_record(obj, fallback_id=None):
        if not isinstance(obj, dict):
            return

        record_id = next(
            (
                obj.get(key)
                for key in id_fields
                if isinstance(obj.get(key), str) and obj.get(key)
            ),
            None,
        )

        if not record_id:
            record_id = fallback_id

        if record_id:
            data[record_id] = obj

    for file in folder_path.rglob("*.json"):
        try:
            with file.open("r", encoding="utf-8") as f:
                content = json.load(f)

            if isinstance(content, dict):
                add_record(content, file.stem)

                for value in content.values():
                    if isinstance(value, dict):
                        add_record(value)
                    elif isinstance(value, list):
                        for item in value:
                            add_record(item)

            elif isinstance(content, list):
                for item in content:
                    add_record(item)

        except (json.JSONDecodeError, OSError) as e:
            print(f"Could not read {file}: {e}")

    return data


def _identity(record):
    identity = record.get("identity", {}) if isinstance(record, dict) else {}
    return identity if isinstance(identity, dict) else {}


def _first_name(merchant):
    identity = _identity(merchant)
    return (
        identity.get("owner_first_name")
        or identity.get("owner_name")
        or "there"
    )


def _merchant_name(merchant):
    return _identity(merchant).get("name") or "your business"


def _customer_name(customer):
    return _identity(customer).get("name") or "there"


def _readable_date(value):
    """Format ISO dates/timestamps for messages."""
    if not isinstance(value, str) or not value:
        return value

    try:
        from datetime import datetime

        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y, %I:%M %p").replace(
            ", 12:00 AM", ""
        )
    except ValueError:
        return value


def _pct(value):
    """Convert decimal percentage values such as -0.5 to -50%."""
    if not isinstance(value, (int, float)):
        return None

    return f"{value * 100:.0f}%"


def _find_digest_item(category, item_id):
    if not item_id:
        return None

    digest = category.get("digest", [])

    if isinstance(digest, dict):
        digest = list(digest.values())

    if isinstance(digest, list):
        for item in digest:
            if isinstance(item, dict) and item.get("id") == item_id:
                return item

    return None


def _offer_text(merchant):
    """Return a service and price phrase when available."""
    offers = merchant.get("offers", [])

    if isinstance(offers, dict):
        offers = list(offers.values())

    if not isinstance(offers, list):
        return None

    for offer in offers:
        if not isinstance(offer, dict):
            continue

        name = (
            offer.get("name")
            or offer.get("title")
            or offer.get("service")
            or offer.get("label")
        )
        price = offer.get("price")

        if name and price is not None:
            return f"{name} @ ₹{price}"

    return None


def _validate_suppression_key(key, customer, merchant):
    """
    Check whether a suppression key appears to reference a different
    customer or merchant.

    This is a diagnostic check only. It does not rewrite the key,
    because the challenge's required format must be followed.
    """
    if not isinstance(key, str) or not key:
        return

    customer_id = None
    merchant_id = None

    if isinstance(customer, dict):
        customer_id = (
            customer.get("customer_id")
            or customer.get("id")
        )

    if isinstance(merchant, dict):
        merchant_id = (
            merchant.get("merchant_id")
            or merchant.get("id")
        )

    if customer_id and str(customer_id) not in key:
        print(
            f"Warning: suppression key {key!r} does not contain "
            f"customer ID {customer_id!r}"
        )

    if merchant_id and str(merchant_id) not in key:
        print(
            f"Warning: suppression key {key!r} does not contain "
            f"merchant ID {merchant_id!r}"
        )


def compose(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: dict | None
) -> dict:
    """
    Compose a concise Vera message.

    Output:
      body, cta, send_as, suppression_key, rationale
    """
    owner = _first_name(merchant)
    merchant_name = _merchant_name(merchant)
    kind = trigger.get("kind", "")
    payload = trigger.get("payload", {}) or {}

    suppression_key = trigger.get("suppression_key", "")

    _validate_suppression_key(
        suppression_key,
        customer,
        merchant
    )

    send_as = "merchant_on_behalf" if customer else "vera"

    body = f"Hi {owner}, I have a useful update for {merchant_name}."
    cta = None
    rationale = (
        "Uses the trigger and merchant context to make the message specific."
    )

    # MERCHANT-FACING TRIGGERS

    if kind == "active_planning_intent":
        topic = payload.get("intent_topic", "")
        last_message = payload.get("merchant_last_message", "")

        if topic == "corporate_bulk_thali_package":
            body = (
                f"Hi {owner}, for the corporate bulk-thali idea you asked "
                f"about, I can help turn it into a simple package with "
                f"quantity, menu and pricing. Reply YES and I'll draft "
                f"the package."
            )
        elif topic == "kids_yoga_summer_camp":
            body = (
                f"Hi {owner}, for the kids' yoga summer camp you asked "
                f"about, I can draft a simple program structure with "
                f"sessions, age group and pricing. Reply YES and I'll "
                f"draft it."
            )
        else:
            body = (
                f"Hi {owner}, picking up your planning request"
                f"{': ' + last_message if last_message else ''}. "
                f"Reply YES and I'll turn it into a concrete draft."
            )

        cta = "YES/STOP"
        rationale = (
            "Continues an explicit merchant planning intent and offers "
            "a concrete next step instead of asking another qualifying question."
        )

    elif kind == "category_seasonal":
        trends = payload.get("trends", [])
        if not isinstance(trends, list):
            trends = []

        cleaned = []

        for trend in trends[:4]:
            text = str(trend).replace("_demand_", " demand ").replace("_", " ")
            text = re.sub(
                r"([+-]?\d+(?:\.\d+)?)$",
                lambda m: m.group(1) + "%",
                text
            )
            cleaned.append(text)

        trend_text = "; ".join(cleaned)
        category_name = (
            category.get("name")
            or category.get("slug")
            or "your category"
        )

        if trend_text:
            body = (
                f"Hi {owner}, the seasonal signal for {category_name} is "
                f"{trend_text}. A shelf review is recommended. Reply YES "
                f"and I'll draft a focused plan."
            )
        else:
            body = (
                f"Hi {owner}, a seasonal demand shift was flagged for "
                f"{category_name}. Reply YES and I'll help review the next step."
            )

        cta = "YES/STOP"
        rationale = (
            "Uses the supplied seasonal demand signals and the recommended "
            "shelf action to give the merchant a concrete next step."
        )

    elif kind == "cde_opportunity":
        credits = payload.get("credits")
        fee = payload.get("fee", "")
        item = _find_digest_item(
            category,
            payload.get("digest_item_id")
        )

        details = []

        if credits is not None:
            details.append(f"{credits} credits")

        if fee:
            details.append(str(fee).replace("_", " "))

        if item:
            title = item.get("title") or item.get("name")
            if title:
                details.insert(0, title)

        detail_text = "; ".join(details)

        body = (
            f"Hi {owner}, there's a dentist CDE opportunity"
            f"{': ' + detail_text if detail_text else ''}. "
            f"Reply YES and I'll pull the details."
        )

        cta = "YES/STOP"
        rationale = (
            "Highlights the supplied professional-development opportunity "
            "and makes the next step low effort."
        )

    elif kind == "competitor_opened":
        competitor = payload.get("competitor_name")
        distance = payload.get("distance_km")
        offer = payload.get("their_offer")

        if competitor and distance is not None and offer:
            body = (
                f"Hi {owner}, {competitor} has opened {distance} km away "
                f"and is advertising {offer}. Worth responding with your "
                f"own positioning. Reply YES and I'll help draft it."
            )
        else:
            body = (
                f"Hi {owner}, a nearby competitor signal has been flagged "
                f"for {merchant_name}. Reply YES and I'll help you assess "
                f"a response."
            )

        cta = "YES/STOP"
        rationale = (
            "Surfaces only the competitor facts present in the trigger "
            "and offers a practical response rather than inventing a counter-offer."
        )

    elif kind == "curious_ask_due":
        ask_template = payload.get("ask_template")

        if ask_template == "what_service_in_demand_this_week":
            body = (
                f"Hi {owner}, quick one: want to know which service is "
                f"showing the strongest demand this week for your category?"
            )
        else:
            body = (
                f"Hi {owner}, quick question for {merchant_name}: "
                f"want this week's most useful demand signal?"
            )

        cta = "YES/STOP"
        rationale = (
            "Uses the trigger's curiosity prompt to invite a low-friction merchant reply."
        )

    elif kind == "dormant_with_vera":
        days = payload.get("days_since_last_merchant_message")
        last_topic = payload.get("last_topic")

        if days and last_topic:
            body = (
                f"Hi {owner}, it's been {days} days since we last spoke. "
                f"We last discussed {str(last_topic).replace('_', ' ')}. "
                f"Reply YES if you'd like a fresh update."
            )
        else:
            body = (
                f"Hi {owner}, it's been a while since we last connected. "
                f"Reply YES if you'd like a useful update for {merchant_name}."
            )

        cta = "YES/STOP"
        rationale = (
            "Uses the dormancy signal to restart the conversation without a generic promotion."
        )

    elif kind == "festival_upcoming":
        festival = payload.get("festival")
        date = payload.get("date")

        if festival and date:
            body = (
                f"Hi {owner}, {festival} is on {_readable_date(date)}. "
                f"It's a useful planning window for {merchant_name}. "
                f"Reply YES and I'll suggest a category-relevant plan."
            )
        else:
            body = (
                f"Hi {owner}, an upcoming festival planning window is "
                f"flagged for {merchant_name}. Reply YES and I'll suggest "
                f"a relevant plan."
            )

        cta = "YES/STOP"
        rationale = (
            "Connects the upcoming event to merchant planning using only "
            "the supplied trigger data."
        )

    elif kind == "gbp_unverified":
        verified = payload.get("verified")
        path = payload.get("verification_path")

        if verified is False and path:
            body = (
                f"Hi {owner}, your Google Business Profile is still "
                f"unverified. The available verification path is "
                f"{str(path).replace('_', ' ')}. Reply YES and I'll walk "
                f"you through the next step."
            )
        else:
            body = (
                f"Hi {owner}, your Google Business Profile verification "
                f"needs attention. Reply YES and I'll help with the next step."
            )

        cta = "YES/STOP"
        rationale = (
            "Uses the explicit GBP verification state and supplied verification path."
        )

    elif kind == "ipl_match_today":
        match = payload.get("match")
        venue = payload.get("venue")
        time = payload.get("match_time_iso")

        match_label = match or "Today's match"
        venue_label = venue or "the listed venue"

        body = (
            f"Hi {owner}, {match_label} is at {venue_label}"
            f"{' at ' + str(_readable_date(time)) if time else ''}. "
            f"Reply YES and I'll help turn the match window into a simple "
            f"restaurant plan."
        )

        cta = "YES/STOP"
        rationale = (
            "Uses the supplied match, venue and time to make a timely local-demand nudge."
        )

    elif kind == "milestone_reached":
        metric = payload.get("metric")
        now = payload.get("value_now")
        milestone = payload.get("milestone_value")
        imminent = payload.get("is_imminent")

        if (
            metric == "review_count"
            and isinstance(now, (int, float))
            and isinstance(milestone, (int, float))
        ):
            body = (
                f"Hi {owner}, you're at {now} reviews and the next "
                f"milestone is {milestone}. That's only {milestone - now} "
                f"reviews away. Reply YES and I'll suggest a simple "
                f"review-collection nudge."
            )
        elif imminent:
            body = (
                f"Hi {owner}, you're close to a milestone on "
                f"{str(metric or 'your account').replace('_', ' ')}. "
                f"Reply YES and I'll help turn it into a focused next step."
            )
        else:
            body = (
                f"Hi {owner}, a milestone update was triggered for "
                f"{merchant_name}. Reply YES and I'll suggest a next step."
            )

        cta = "YES/STOP"
        rationale = (
            "Uses the supplied milestone information to create a specific, actionable nudge."
        )

    elif kind == "perf_dip":
        metric = payload.get("metric")
        delta = _pct(payload.get("delta_pct"))
        window = payload.get("window")
        baseline = payload.get("vs_baseline")

        if metric and delta:
            change = abs(float(payload.get("delta_pct")) * 100)
            body = (
                f"Hi {owner}, {metric} are down {change:.0f}% "
                f"{'over ' + str(window) if window else 'in the recent window'}"
                f"{' vs a baseline of ' + str(baseline) if baseline is not None else ''}. "
                f"Reply YES and I'll help diagnose the drop."
            )
        else:
            body = (
                f"Hi {owner}, your recent performance has dipped. "
                f"Reply YES and I'll help identify the likely next action."
            )

        cta = "YES/STOP"
        rationale = (
            "Uses the supplied performance movement and offers diagnosis rather than inventing a cause."
        )

    elif kind == "perf_spike":
        metric = payload.get("metric")
        delta = _pct(payload.get("delta_pct"))
        driver = payload.get("likely_driver")

        if metric and delta:
            body = (
                f"Hi {owner}, {metric} are up {delta.lstrip('+')} in the "
                f"recent window"
                f"{' — likely linked to ' + str(driver).replace('_', ' ') if driver else ''}. "
                f"Reply YES and I'll help build on the signal."
            )
        else:
            body = (
                f"Hi {owner}, there's a positive performance signal for "
                f"{merchant_name}. Reply YES and I'll help identify what to repeat."
            )

        cta = "YES/STOP"
        rationale = (
            "Uses the observed performance spike and, when available, its supplied likely driver."
        )

    elif kind == "regulation_change":
        item = _find_digest_item(
            category,
            payload.get("top_item_id")
        )
        deadline = payload.get("deadline_iso")

        if item:
            title = item.get("title") or item.get("name") or "a regulation update"
            body = (
                f"Hi {owner}, regulation update: {title}"
                f"{' Deadline: ' + str(_readable_date(deadline)) if deadline else ''}. "
                f"Reply YES and I'll pull the relevant details."
            )
        else:
            body = (
                f"Hi {owner}, there's a regulation update for your category"
                f"{' with a deadline of ' + str(_readable_date(deadline)) if deadline else ''}. "
                f"Reply YES and I'll pull the relevant details."
            )

        cta = "YES/STOP"
        rationale = (
            "Surfaces the supplied regulation item and deadline without adding unsupported compliance claims."
        )

    # CUSTOMER-FACING TRIGGERS

    elif kind == "appointment_tomorrow":
        name = _customer_name(customer)
        body = (
            f"Hi {name}, a reminder from {merchant_name}: your appointment "
            f"is tomorrow. Reply YES to confirm or STOP to opt out of reminders."
        )
        cta = "YES/STOP"
        rationale = (
            "Uses the appointment trigger and customer identity for a concise reminder."
        )

    elif kind == "chronic_refill_due":
        name = _customer_name(customer)
        runout = payload.get("stock_runs_out_iso")

        if payload.get("molecule_list"):
            address_note = (
                " A saved delivery address is available."
                if payload.get("delivery_address_saved") is True
                else ""
            )
            body = (
                f"Hi {name}, your refill reminder from {merchant_name} is due"
                f"{' before ' + str(_readable_date(runout)) if runout else ''}. "
                f"Reply YES if you'd like us to check the refill arrangements."
                f"{address_note}"
            )
        else:
            body = (
                f"Hi {name}, your refill reminder from {merchant_name} is due. "
                f"Reply YES if you'd like us to arrange it."
            )

        cta = "YES/STOP"
        rationale = (
            "Uses the refill timing and saved delivery context while avoiding unsupported medical advice."
        )

    elif kind == "customer_lapsed_hard":
        name = _customer_name(customer)
        days = payload.get("days_since_last_visit")

        detail = (
            f" — it's been {days} days since your last visit"
            if days is not None
            else ""
        )

        body = (
            f"Hi {name}, {merchant_name} would be happy to have you back"
            f"{detail}. Reply YES and we can help with your next visit."
        )

        cta = "YES/STOP"
        rationale = (
            "Uses the customer's prior relationship with the merchant to make a respectful win-back message."
        )

    elif kind == "customer_lapsed_soft":
        name = _customer_name(customer)
        body = (
            f"Hi {name}, it's been a little while since your last visit "
            f"to {merchant_name}. Would you like help planning your next visit? "
            f"Reply YES."
        )
        cta = "YES/STOP"
        rationale = (
            "Uses the customer's lapsed state for a soft, non-promotional re-engagement."
        )

    elif kind == "recall_due":
        name = _customer_name(customer)
        service = payload.get("service_due")
        slots = payload.get("available_slots", [])

        slot_text = ""

        if isinstance(slots, list):
            labels = [
                slot.get("label")
                for slot in slots[:2]
                if isinstance(slot, dict) and slot.get("label")
            ]
            if labels:
                slot_text = " Available: " + " or ".join(labels) + "."

        service_text = (
            str(service).replace("_", " ")
            if service
            else "your next recall"
        )

        body = (
            f"Hi {name}, {merchant_name} has a reminder for {service_text}."
            f"{slot_text} Reply YES if you'd like us to help book a slot."
        )
        cta = "YES/STOP"
        rationale = (
            "Uses the due service and supplied appointment slots to make the recall reminder actionable."
        )

    elif kind == "research_digest":
        item = _find_digest_item(
            category,
            payload.get("top_item_id")
        )
        item = item or payload.get("top_item")

        if isinstance(item, dict):
            title = (
                item.get("title")
                or item.get("headline")
                or item.get("name")
            )
            action = (
                item.get("actionable")
                or item.get("suggested_action")
            )

            if title:
                body = f"Hi {owner}, {title}"
                if action:
                    body += f" {action}"
                cta = "YES/STOP" if action else None
                rationale = (
                    "Shares the supplied category research and its supported action, when available."
                )
            else:
                body = (
                    f"Hi {owner}, I have a category research update for "
                    f"{merchant_name}. Reply YES if you'd like the details."
                )
                cta = "YES/STOP"
                rationale = (
                    "Offers the available research context without inventing a finding."
                )
        else:
            body = (
                f"Hi {owner}, I have a category research update for "
                f"{merchant_name}. Reply YES if you'd like the details."
            )
            cta = "YES/STOP"
            rationale = (
                "Offers a relevant research update without fabricating its contents."
            )

    elif kind == "renewal_due":
        days = payload.get("days_remaining")
        plan = payload.get("plan")
        amount = payload.get("renewal_amount")

        details = []
        if plan:
            details.append(str(plan))
        if amount is not None:
            details.append(f"₹{amount}")

        detail = " · ".join(details)
        body = f"Hi {owner}, your {detail + ' ' if detail else ''}plan renewal is due"

        if days is not None:
            body += f" in {days} days"

        body += ". Reply YES if you'd like help reviewing the renewal."
        cta = "YES/STOP"
        rationale = (
            "Uses the supplied renewal timing and plan details to offer a clear next step."
        )

    elif kind == "winback_eligible":
        name = _customer_name(customer)
        days = payload.get("days_since_last_visit")
        detail = (
            f" It's been {days} days since your last visit."
            if days is not None
            else ""
        )

        body = (
            f"Hi {name}, {merchant_name} would be glad to welcome you back."
            f"{detail} Reply YES if you'd like help planning a visit."
        )
        cta = "YES/STOP"
        rationale = (
            "Uses a respectful, low-pressure re-engagement message without exposing personal history."
        )

    elif kind == "review_theme_emerged":
        theme = payload.get("theme") or payload.get("review_theme")
        count = payload.get("count") or payload.get("mentions")

        if theme:
            body = (
                f"Hi {owner}, recent reviews are highlighting "
                f"{str(theme).replace('_', ' ')}"
            )
            if count is not None:
                body += f" ({count} mentions)"
            body += ". Reply YES and I'll help draft a response or improvement step."
        else:
            body = (
                f"Hi {owner}, a theme has emerged in recent customer reviews "
                f"for {merchant_name}. Reply YES and I'll share the details."
            )

        cta = "YES/STOP"
        rationale = (
            "Turns a supplied review theme into a practical response without inventing review content."
        )

    elif kind == "seasonal_perf_dip":
        metric = payload.get("metric")
        delta = _pct(payload.get("delta_pct"))

        if metric:
            body = (
                f"Hi {owner}, {metric} have dipped"
                f"{f' by {delta}' if delta else ''} during the seasonal window. "
                f"Reply YES and I'll help review the available signals."
            )
        else:
            body = (
                f"Hi {owner}, a seasonal performance dip was flagged for "
                f"{merchant_name}. Reply YES and I'll help review it."
            )

        cta = "YES/STOP"
        rationale = (
            "Connects the seasonal performance signal to a review step without assuming its cause."
        )

    elif kind == "trial_followup":
        program = (
            payload.get("program")
            or payload.get("trial_name")
            or "the trial"
        )
        body = (
            f"Hi {owner}, following up on {program}. Would you like to "
            f"turn the trial feedback into a next-step plan? Reply YES."
        )
        cta = "YES/STOP"
        rationale = (
            "Follows up on the supplied trial context with one clear action."
        )

    elif kind == "supply_alert":
        item = (
            payload.get("item")
            or payload.get("product")
            or payload.get("molecule")
        )
        status = payload.get("status") or payload.get("alert")
        detail = " — ".join(str(x) for x in (item, status) if x)

        body = (
            f"Hi {owner}, a supply alert was flagged"
            f"{': ' + detail if detail else ''}. Please verify stock "
            f"before making customer commitments. Reply YES if you'd "
            f"like help reviewing the alert."
        )
        cta = "YES/STOP"
        rationale = (
            "Surfaces the supplied stock alert and encourages verification rather than making availability claims."
        )

    elif kind == "wedding_package_followup":
        package = payload.get("package") or payload.get("package_name")
        body = (
            f"Hi {owner}, following up on the wedding package"
            f"{': ' + str(package) if package else ''}. "
            f"Reply YES and I'll help prepare the next-step details."
        )
        cta = "YES/STOP"
        rationale = (
            "Continues the supplied package discussion with a concrete, low-effort next step."
        )

    else:
        if customer:
            name = _customer_name(customer)
            body = (
                f"Hi {name}, {merchant_name} has an update for you. "
                f"Reply YES if you'd like more details."
            )
            cta = "YES/STOP"
            rationale = (
                "Uses customer and merchant context without inventing trigger-specific facts."
            )
        else:
            body = (
                f"Hi {owner}, I have a relevant update for {merchant_name}. "
                f"Reply YES and I'll share the details."
            )
            cta = "YES/STOP"
            rationale = (
                "Uses merchant context and provides a low-friction action without fabricating details."
            )

    return {
        "body": body,
        "cta": cta,
        "send_as": send_as,
        "suppression_key": suppression_key,
        "rationale": rationale,
    }


def main():
    print("Loading dataset...")

    categories = load_folder("categories")
    merchants = load_folder("merchants")
    customers = load_folder("customers")
    triggers = load_folder("triggers")

    print(f"Categories loaded: {len(categories)}")
    print(f"Merchants loaded: {len(merchants)}")
    print(f"Customers loaded: {len(customers)}")
    print(f"Triggers loaded: {len(triggers)}")

    test_file = DATASET / "test_pairs.json"

    if not test_file.exists():
        print(f"ERROR: test_pairs.json not found at {test_file}")
        return

    with test_file.open("r", encoding="utf-8") as f:
        test_data = json.load(f)

    test_pairs = (
        test_data.get("pairs", [])
        if isinstance(test_data, dict)
        else test_data
    )

    print(f"Test pairs found: {len(test_pairs)}")

    output = []
    errors = []

    for pair in test_pairs:
        test_id = pair.get("test_id")
        trigger_id = pair.get("trigger_id")
        merchant_id = pair.get("merchant_id")
        customer_id = pair.get("customer_id")

        trigger = triggers.get(trigger_id)
        merchant = merchants.get(merchant_id)

        if not trigger:
            errors.append(f"{test_id}: Missing trigger {trigger_id}")
            continue

        if not merchant:
            errors.append(f"{test_id}: Missing merchant {merchant_id}")
            continue

        category_slug = merchant.get("category_slug")
        category = categories.get(category_slug)

        if not category:
            errors.append(f"{test_id}: Missing category {category_slug}")
            continue

        customer = None

        if customer_id:
            customer = customers.get(customer_id)

            if not customer:
                errors.append(f"{test_id}: Missing customer {customer_id}")
                continue

        result = compose(category, merchant, trigger, customer)
        output.append({"test_id": test_id, **result})

    output_file = BASE_DIR / "submission.jsonl"

    with output_file.open("w", encoding="utf-8") as f:
        for item in output:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print("\nProcessing complete!")
    print(f"Successful submissions: {len(output)}")
    print(f"Errors: {len(errors)}")
    print(f"Output file: {output_file}")

    if errors:
        print("\nErrors found:")
        for error in errors:
            print("-", error)


if __name__ == "__main__":
    main()