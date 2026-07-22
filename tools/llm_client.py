"""
LLM client abstraction.
Supports xAI Grok (primary), OpenAI (fallback), and a regex-based Mock (no API key needed).
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from config import Config


# ── Public factory ─────────────────────────────────────────────────────────────

def get_llm_client():
    provider = Config.resolved_provider()
    if provider == "xai":
        return _OpenAICompatibleClient(
            api_key=Config.XAI_API_KEY,
            base_url=Config.XAI_BASE_URL,
            model=Config.XAI_MODEL,
            provider_name="xAI Grok",
        )
    if provider == "openai":
        return _OpenAICompatibleClient(
            api_key=Config.OPENAI_API_KEY,
            base_url=None,
            model=Config.OPENAI_MODEL,
            provider_name="OpenAI",
        )
    return _MockLLMClient()


# ── Real LLM (OpenAI-compatible) ───────────────────────────────────────────────

class _OpenAICompatibleClient:
    def __init__(self, api_key: str, base_url: Optional[str], model: str, provider_name: str):
        from openai import OpenAI
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model
        self.provider_name = provider_name

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> dict:
        kwargs: dict[str, Any] = {"model": self._model, "messages": messages, "temperature": 0}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"
        response = self._client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        if tools and msg.tool_calls:
            call = msg.tool_calls[0]
            return {
                "type": "tool_call",
                "name": call.function.name,
                "arguments": json.loads(call.function.arguments),
            }
        return {"type": "text", "content": msg.content or ""}


# ── Mock LLM (regex heuristics, no API key) ────────────────────────────────────

class _MockLLMClient:
    provider_name = "Mock (no API key)"

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> dict:
        user_content = next(
            (m["content"] for m in messages if m.get("role") == "user"), ""
        )
        sys_content = next(
            (m["content"] for m in messages if m.get("role") == "system"), ""
        )

        if tools and "extract_invoice_data" in str([t.get("function", {}).get("name") for t in tools]):
            return {"type": "tool_call", "name": "extract_invoice_data", "arguments": self._mock_extract(user_content)}

        if tools and "submit_approval_decision" in str([t.get("function", {}).get("name") for t in tools]):
            return {"type": "tool_call", "name": "submit_approval_decision", "arguments": self._mock_approve(user_content)}

        return {"type": "text", "content": self._mock_critique(user_content)}

    # ── Extraction heuristics ─────────────────────────────────────────────────

    def _mock_extract(self, text: str) -> dict:
        # Strip the LLM prompt preamble — invoice content starts after first blank line
        if "\n\n" in text:
            text = text[text.index("\n\n") + 2:]

        # Fast-path: structured formats
        stripped = text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            return self._mock_extract_json(stripped)
        if stripped.startswith("CSV Invoice Data:"):
            return self._mock_extract_csv(stripped)

        invoice_id = self._find(r"\b(INV-\d+)\b", text, flags=re.IGNORECASE)
        vendor = self._find_vendor(text)
        amount = self._find_amount(text)
        due_date = self._find_date(text)
        items = self._find_items(text)
        confidence = self._compute_confidence(invoice_id, vendor, amount, items)

        return {
            "invoice_id": invoice_id,
            "vendor": vendor.strip() if vendor else None,
            "amount": amount,
            "due_date": due_date,
            "items": items,
            "extraction_confidence": confidence,
            "extraction_notes": "" if confidence > 0.7 else "Some fields could not be auto-extracted",
        }

    def _mock_extract_json(self, text: str) -> dict:
        """Parse a JSON-formatted invoice directly."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Malformed JSON — fall through to regex extraction
            return self._mock_extract_regex_only(text)

        # Normalise keys: handle both 'description' and 'name' for items
        raw_items = data.get("items") or data.get("line_items") or []
        items = []
        for it in raw_items:
            name = it.get("description") or it.get("name") or it.get("item") or ""
            qty = it.get("quantity") or it.get("qty") or 1
            unit_price = it.get("unit_price") or it.get("price") or None
            total = it.get("line_total") or it.get("total") or it.get("total_price") or None
            items.append({"name": name, "quantity": qty, "unit_price": unit_price, "total_price": total})

        vendor = data.get("vendor") or data.get("vendor_name") or data.get("from") or None
        amount = (
            data.get("total") or data.get("amount") or data.get("total_due")
            or data.get("invoice_total") or data.get("grand_total") or None
        )
        due_date = data.get("due_date") or data.get("payment_due") or data.get("due") or None
        invoice_id = data.get("invoice_id") or data.get("invoice_number") or None
        confidence = self._compute_confidence(invoice_id, vendor, amount, items)
        return {
            "invoice_id": invoice_id,
            "vendor": vendor,
            "amount": float(amount) if amount else None,
            "due_date": due_date,
            "items": items,
            "extraction_confidence": confidence,
            "extraction_notes": "Parsed directly from JSON format",
        }

    def _mock_extract_csv(self, text: str) -> dict:
        """Parse CSV Invoice Data: key: value, key: value rows."""
        rows = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("CSV")]
        if not rows:
            return self._mock_extract_regex_only(text)

        # Parse first row for header fields
        def parse_row(row: str) -> dict:
            parts = [p.strip() for p in row.lstrip("- ").split(", ")]
            result = {}
            for part in parts:
                if ": " in part:
                    k, v = part.split(": ", 1)
                    result[k.strip()] = v.strip()
            return result

        first = parse_row(rows[0])
        invoice_id = first.get("invoice_id")
        vendor = first.get("vendor")
        due_date = first.get("due_date")
        # total from any row
        total_val = first.get("invoice_total") or first.get("total") or first.get("amount")
        amount = float(total_val) if total_val else None

        items = []
        for row in rows:
            d = parse_row(row)
            item_name = d.get("item") or d.get("name") or d.get("description")
            if item_name:
                qty_str = d.get("quantity") or d.get("qty") or "1"
                up_str = d.get("unit_price") or d.get("price")
                items.append({
                    "name": item_name,
                    "quantity": float(qty_str),
                    "unit_price": float(up_str) if up_str else None,
                })
        confidence = self._compute_confidence(invoice_id, vendor, amount, items)
        return {
            "invoice_id": invoice_id,
            "vendor": vendor,
            "amount": amount,
            "due_date": due_date,
            "items": items,
            "extraction_confidence": confidence,
            "extraction_notes": "Parsed from CSV format",
        }

    def _mock_extract_regex_only(self, text: str) -> dict:
        """Regex extraction without JSON pre-check (avoids recursion)."""
        invoice_id = self._find(r"\b(INV-\d+)\b", text, flags=re.IGNORECASE)
        vendor = self._find_vendor(text)
        amount = self._find_amount(text)
        due_date = self._find_date(text)
        items = self._find_items(text)
        confidence = self._compute_confidence(invoice_id, vendor, amount, items)
        return {
            "invoice_id": invoice_id,
            "vendor": vendor.strip() if vendor else None,
            "amount": amount,
            "due_date": due_date,
            "items": items,
            "extraction_confidence": confidence,
            "extraction_notes": "" if confidence > 0.7 else "Some fields could not be auto-extracted",
        }

    def _find(self, pattern: str, text: str, flags: int = re.IGNORECASE) -> Optional[str]:
        m = re.search(pattern, text, flags)
        return m.group(1).strip() if m else None

    def _find_vendor(self, text: str) -> Optional[str]:
        """Extract vendor name robustly from multiple invoice layouts."""
        # 1. Explicit single-line "Vendor:" label
        m = re.search(r"^\s*vendor\s*:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
        if m:
            val = m.group(1).strip()
            if len(val) > 2:
                return val

        # 2. "Invoice from:" label
        m = re.search(r"invoice\s+from\s*:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()

        # 3. Two-column layout: "FROM:" appears at end of a header line;
        #    vendor name is in the right column of the NEXT line
        m = re.search(r"from\s*:\s*\n(.+)$", text, re.IGNORECASE | re.MULTILINE)
        if m:
            line = m.group(1)
            if re.search(r"\s{4,}", line):
                # Right column = everything after 4+ spaces
                right = re.split(r"\s{4,}", line)[-1].strip()
                if right and len(right) > 2:
                    return right
            return line.strip()

        # 4. Any line that clearly contains a corporate suffix
        corp_m = re.search(
            r"^[ \t]*([A-Z][^\n]{2,50}(?:Inc\.|Corp\b|LLC\b|Ltd\b|Co\.|Solutions|Industries|Supplies|Parts)\.?)\s*$",
            text, re.IGNORECASE | re.MULTILINE,
        )
        if corp_m:
            return corp_m.group(1).strip()

        return None

    def _find_amount(self, text: str) -> Optional[float]:
        # More-specific patterns first; use \b to avoid matching "Subtotal"
        patterns = [
            r"(?:total\s*due|amount\s*due|grand\s*total|invoice\s*total)[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"^\s*TOTAL[:\s]+\$?\s*([\d,]+\.?\d*)\s*$",
            r"(?<!\w)total(?!\w)[:\s]*\$?\s*([\d,]+\.?\d*)",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE | re.MULTILINE)
            if m:
                try:
                    val = float(m.group(1).replace(",", ""))
                    if val > 0:
                        return val
                except ValueError:
                    pass
        # Last resort: find last positive dollar amount
        amounts = re.findall(r"\$\s*([\d,]+\.\d{2})", text)
        for a in reversed(amounts):
            try:
                v = float(a.replace(",", ""))
                if v > 0:
                    return v
            except ValueError:
                pass
        return None

    def _find_date(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:due\s*date|payment\s*due|pay\s*by)[:\s]+(\d{4}-\d{2}-\d{2})",
            r"(?:due\s*date|payment\s*due|pay\s*by)[:\s]+(\w+\s+\d{1,2},?\s+\d{4})",
            r"(?:due\s*date|payment\s*due|pay\s*by)[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    def _find_items(self, text: str) -> list[dict]:
        items = []
        # Pattern: item name × qty @ price
        patterns = [
            # Unicode × or * as multiplier (NOT ASCII x — avoids "GadgetX" false-positive)
            r"([A-Za-z][A-Za-z0-9\s]*?)\s*[×\*]\s*(\d+)\s*(?:units?)?\s*@?\s*\$?([\d,]+\.?\d*)",
            # "item – qty: N" notation
            r"([A-Za-z][A-Za-z0-9\s]*?)\s+[–-]\s+(?:qty|quantity)[:\s]+(-?\d+)",
            # Column-aligned table: must start at line-beginning, single-word CamelCase names
            # (two-word proper noun addresses like "Manufacturing Dr" are excluded by the ^ anchor
            #  + the fact that address lines start with digits "123 ..." which fail [A-Z] match)
            r"^[ \t]*([A-Z][a-z]+[A-Za-z0-9]*)\s{2,}(-?\d+)\s{2,}\$?([\d,]+\.?\d*)",
        ]
        _NOISE = {
            "item", "description", "qty", "quantity", "unit", "line", "total",
            "subtotal", "grand", "amount", "due", "discount", "tax", "shipping",
            "freight", "handling", "payment", "invoice", "date", "vendor", "from",
            "bill", "please", "note", "thank", "contact",
        }
        seen = set()
        for p in patterns:
            for m in re.finditer(p, text, re.IGNORECASE | re.MULTILINE):
                name = m.group(1).strip()
                # Filter out noise words and lines with special chars that aren't item names
                if name.lower() in _NOISE:
                    continue
                # Skip names containing % or that look like financial line items
                if "%" in name or name.startswith("-") or re.match(r"^[\d\s\$\.,\-]+$", name):
                    continue
                if name in seen:
                    continue
                seen.add(name)
                try:
                    qty = float(m.group(2).replace(",", ""))
                except (IndexError, ValueError):
                    qty = 1.0
                unit_price = None
                if len(m.groups()) >= 3:
                    try:
                        unit_price = float(m.group(3).replace(",", ""))
                    except (IndexError, ValueError, AttributeError):
                        pass
                items.append({"name": name, "quantity": qty, "unit_price": unit_price})
        return items

    def _compute_confidence(self, invoice_id, vendor, amount, items) -> float:
        score = 0.0
        if invoice_id:
            score += 0.2
        if vendor:
            score += 0.3
        if amount is not None:
            score += 0.3
        if items:
            score += 0.2
        return score

    # ── Approval heuristics ───────────────────────────────────────────────────

    def _mock_approve(self, text: str) -> dict:
        risk = 0.1
        flags = []
        tl = text.lower()

        # Fraud signals
        if "fakeitem" in tl:
            risk += 0.5
            flags.append("Fraudulent/zero-stock item detected")
        if "quickbucks" in tl or "shady" in tl:
            risk += 0.3
            flags.append("Suspicious vendor name")
        if "fraud_indicator" in tl:
            risk += 0.2
            flags.append("Fraud indicator flagged by validation")

        # Inventory failures — only penalise ERROR-level flags (not warnings)
        # Context format: [ERROR][flag_type] or [WARN][flag_type]
        if re.search(r"\[error\]\[stock_mismatch\]", tl) or re.search(r"only \d+ in stock", tl):
            risk += 0.35
            flags.append("Stock quantity mismatch (ERROR)")
        if re.search(r"\[error\]\[out_of_stock\]", tl) or "zero stock" in tl:
            risk += 0.4
            flags.append("Out-of-stock item (ERROR)")
        if re.search(r"\[error\]\[unknown_item\]", tl):
            risk += 0.35
            flags.append("Unknown/uncatalogued item (ERROR)")
        if re.search(r"\[error\]\[negative_quantity\]", tl) or "negative quantity" in tl:
            risk += 0.45
            flags.append("Negative quantity — data integrity (ERROR)")
        if re.search(r"\[error\]\[data_integrity\]", tl):
            risk += 0.3
            flags.append("Data integrity issue (ERROR)")

        # Validation result summary
        err_m = re.search(r"(\d+) errors", tl)
        if err_m and int(err_m.group(1)) > 0:
            err_count = int(err_m.group(1))
            risk += min(0.3, err_count * 0.15)
            flags.append(f"{err_count} validation error(s)")

        # Urgency language
        if re.search(r"\b(urgent|asap|immediate|rush)\b", tl):
            risk += 0.1
            flags.append("Urgent payment pressure")

        # Amount-based risk
        amt_m = re.search(r"\$([\d,]+\.?\d*)", text)
        if amt_m:
            try:
                amt = float(amt_m.group(1).replace(",", ""))
                if amt > 50_000:
                    risk += 0.3
                    flags.append("Exceptionally high amount")
                elif amt > 10_000:
                    risk += 0.1
                    flags.append("High-value invoice — extra scrutiny applied")
            except ValueError:
                pass

        risk = min(risk, 1.0)
        decision = "REJECTED" if risk > 0.40 else "APPROVED"
        reasoning = (
            f"Risk score {risk:.2f}. " + ("; ".join(flags) if flags else "No significant concerns identified.")
        )
        return {
            "decision": decision,
            "reasoning": reasoning,
            "risk_score": risk,
            "requires_escalation": risk > 0.6,
        }

    # ── Critique heuristics ───────────────────────────────────────────────────

    def _mock_critique(self, text: str) -> str:
        if "approved" in text.lower() and ("fakeitem" in text.lower() or "suspicious" in text.lower()):
            return (
                "CRITIQUE: This approval is questionable. The invoice contains suspicious indicators "
                "that were not sufficiently weighted. Recommend rejection."
            )
        if "rejected" in text.lower() and "within stock" in text.lower() and "no flags" in text.lower():
            return (
                "CRITIQUE: The rejection appears overly cautious. All items are in stock and "
                "no validation flags were raised. Consider approval."
            )
        return "CRITIQUE: The decision appears reasonable given the available evidence."
