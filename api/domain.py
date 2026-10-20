"""Code owns money, verdicts, dates, masking, and edit-distance metrics."""
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Money = Decimal


def cents(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(value):
    return f"{Decimal(value) / 100:.2f}"


def mask(text):
    text = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", "[email removed]", str(text))
    text = re.sub(r"\b(?:\+?\d[\d ()-]{7,}\d)\b", "[identifier removed]", text)
    text = re.sub(r"(?im)\b(account|customer id|address|phone|mobile|name)\s*[:#].*", r"\1: [removed]", text)
    return text.strip()


class Line(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount: Money = Field(ge=-10000000, le=10000000, decimal_places=2)
    kind: Literal["base", "tax", "extra", "credit", "late_fee"] = "base"
    accepted: bool = False
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=3)
    tax_base: Money | None = Field(default=None, ge=0, le=10000000, decimal_places=2)


class BillInput(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    currency: Literal["INR", "USD", "EUR", "GBP"] = "INR"
    bill_date: date
    period_start: date | None = None
    period_end: date | None = None
    due_date: date | None = None
    paid_date: date | None = None
    total: Money = Field(ge=0, le=10000000, decimal_places=2)
    expected: Money = Field(ge=0, le=10000000, decimal_places=2)
    promise_source: str = Field(default="", max_length=2000)
    promise_date: date | None = None
    promise_includes_tax: bool = True
    expected_tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100, decimal_places=3)
    evidence: str = Field(default="", max_length=3000)
    lines: list[Line] = Field(min_length=1, max_length=100)
    confirmed: bool

    @model_validator(mode="after")
    def check(self):
        if not self.confirmed:
            raise ValueError("Confirm the extracted lines before checking.")
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("Billing period end must follow its start.")
        if self.promise_date and self.promise_date > self.bill_date:
            raise ValueError("The promise must apply on or before the bill date.")
        return self


def analyze(bill: BillInput, previous=None):
    amounts = [cents(line.amount) for line in bill.lines]
    total, expected = cents(bill.total), cents(bill.expected)
    promise_tax = 0 if bill.promise_includes_tax else int(
        (Decimal(expected) * bill.expected_tax_rate / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    expected += promise_tax
    gap = total - expected
    line_sum = sum(amounts)
    issues, details = [], []
    accepted_extras = 0
    for pos, (line, amount) in enumerate(zip(bill.lines, amounts)):
        notes = []
        if line.kind in ("extra", "late_fee", "credit") and line.accepted:
            accepted_extras += amount
            notes.append("You confirmed this adjustment is outside the promised price.")
        if line.kind in ("extra", "late_fee") and not line.accepted:
            issues.append(pos)
            notes.append("Unexplained charge: ask the provider for its basis; this is not proof of an error.")
        if line.kind == "tax":
            if line.tax_rate is not None and line.tax_base is not None:
                calculated = int((Decimal(cents(line.tax_base)) * line.tax_rate / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                notes.append(f"Tax arithmetic: {money(cents(line.tax_base))} × {line.tax_rate}% = {money(calculated)}.")
                if calculated != amount:
                    issues.append(pos)
                    notes.append(f"Tax arithmetic differs by {money(amount - calculated)}. Confirm the taxable base and rounding.")
            else:
                notes.append("Tax not verified: enter the printed rate and taxable base. No tax rate is assumed legally correct.")
        if line.kind == "late_fee":
            if bill.paid_date and bill.due_date:
                notes.append("Payment recorded on or before due date; request an explanation for this fee." if bill.paid_date <= bill.due_date else "Payment date is after the due date; confirm posting and provider terms.")
                if bill.paid_date <= bill.due_date:
                    issues.append(pos)
            else:
                notes.append("Add the payment date and due date to check the late fee.")
        repeats = sorted({old["bill_date"] for old in (previous or []) if
            old["provider"].casefold() == bill.provider.casefold()
            and old["currency"] == bill.currency
            and old["bill_date"][:7] != bill.bill_date.isoformat()[:7]
            and old["description"].casefold() == mask(line.description).casefold()
            and old["amount_cents"] == amount})
        if repeats:
            notes.append("Also appeared on: " + ", ".join(repeats) + ". Repetition alone does not prove an error.")
        details.append({"position": pos, "description": mask(line.description), "amount_cents": amount, "notes": notes, "repeated_on": repeats})
    residual = gap - accepted_extras
    incomplete_tax = any(x.kind == "tax" and (x.tax_rate is None or x.tax_base is None) for x in bill.lines)
    if line_sum != total or residual or issues:
        verdict = "unexplained"
    elif accepted_extras:
        verdict = "explained"
    else:
        verdict = "checks_out"
    missing = []
    if not bill.promise_source.strip():
        missing.append("Add the source of the promised price (plan, email, or conversation).")
    if incomplete_tax:
        missing.append("Tax rates or taxable bases are missing; tax arithmetic remains unverified.")
    if residual:
        missing.append("Which plan change, usage, credit, or adjustment accounts for the remaining difference?")
    if line_sum != total:
        missing.append("The lines do not match the printed total. Check for a missed line, subtotal counted twice, or OCR error.")
    return {
        "verdict": verdict, "total_cents": total, "expected_cents": expected,
        "promise_tax_cents": promise_tax, "line_sum_cents": line_sum,
        "gap_cents": gap, "accepted_extras_cents": accepted_extras,
        "unexplained_cents": residual, "total_mismatch_cents": total - line_sum,
        "flagged_positions": sorted(set(issues)), "lines": details, "missing_info": missing,
        "scope": "Checks use your confirmed inputs. This verifies arithmetic, not whether a fee or tax is legally valid.",
    }


def words_changed(original, final):
    """Word-level Levenshtein distance: substitutions, insertions, deletions."""
    a, b = original.split(), final.split()
    row = list(range(len(b) + 1))
    for i, word in enumerate(a, 1):
        nxt = [i]
        for j, other in enumerate(b, 1):
            nxt.append(min(nxt[-1] + 1, row[j] + 1, row[j - 1] + (word != other)))
        row = nxt
    return row[-1]


def draft_message(bill, result, positions, tone="polite"):
    unit = bill["currency"]
    selected = [result["lines"][p] for p in positions]
    lines = "; ".join(f'{x["description"]} ({unit} {money(x["amount_cents"])})' for x in selected)
    opener = {"polite": "Hello, could you please help me understand my bill?",
              "firm": "Hello, I am requesting a review of my bill.",
              "concise": "Hello, please clarify my bill."}[tone]
    text = (f'{opener}\n\nMy bill from {bill["provider"]} totals {unit} {money(result["total_cents"])}. '
            f'My expected total was {unit} {money(result["expected_cents"])}. '
            f'The difference is {unit} {money(result["gap_cents"])}.')
    if lines:
        text += f"\n\nPlease explain these lines: {lines}."
    if result["total_mismatch_cents"]:
        text += f'\nThe listed lines sum to {unit} {money(result["line_sum_cents"])}, which does not match the printed total.'
    text += "\n\nPlease share the basis for these charges and correct the bill if a charge was applied in error. Thank you."
    return text
