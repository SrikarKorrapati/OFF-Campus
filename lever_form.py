"""Fill one Lever application form with answers approved by the question graph."""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Error as BrowserError, Locator


# Read the current controls together so labels, option lists and values describe the same page.
_READ_FIELDS = r"""form => {
    const fields = new Map();
    const text = node => (node?.textContent || '').replace(/\s+/g, ' ').trim();
    const visible = node => node?.checkVisibility({visibilityProperty: true}) && node.getClientRects().length;
    for (const el of form.querySelectorAll('input, select, textarea, [aria-required="true"]')) {
        const tag = el.localName;
        const kind = tag === 'input' ? el.type : tag;
        if (el.matches(':disabled') || ['hidden','submit','button','reset','image'].includes(kind)) continue;
        const block = el.closest('.application-question, fieldset');
        if (!visible(el) && !(kind === 'file' && visible(block))) continue;
        if (!['input','textarea','select'].includes(tag) && el.querySelector('input,select,textarea')) continue;
        const leverLabel = block?.querySelector('.application-label');
        const heading = leverLabel || block?.querySelector('legend');
        const label = el.labels?.[0]?.cloneNode(true);
        label?.querySelectorAll('input, select, textarea, button').forEach(n => n.remove());
        const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/);
        const named = ids.map(id => text(document.getElementById(id))).filter(Boolean).join(' ')
            || el.getAttribute('aria-label') || text(label);
        const choice = ['checkbox','radio'].includes(kind);
        const required = el.required || el.getAttribute('aria-required') === 'true'
            || !!heading?.querySelector('.required') || /[✱*]\s*$/.test(text(heading) || named);
        const title = text(leverLabel?.querySelector('.text') || leverLabel)
            || (choice ? text(heading) : named) || el.placeholder || (kind === 'checkbox' ? named : '') || el.name || el.id;
        const question = (title || 'Unnamed field').replace(/\s*[✱*]\s*$/, '').trim();
        let selector = el.id ? '#' + CSS.escape(el.id) : '';
        if (!selector && el.name) {
            selector = tag + '[name=' + CSS.escape(el.name) + ']';
            if (choice && el.hasAttribute('value')) selector += '[value="' + CSS.escape(el.value) + '"]';
        }
        if (selector && form.querySelectorAll(selector).length !== 1) selector = '';
        const firstChoice = choice && heading && block.querySelector('input[type=' + kind + ']');
        const key = JSON.stringify([kind, firstChoice?.name || el.name || el.id || question, question]);
        const field = fields.get(key) || {
            key, question, kind, required: false, selector, options: [], value: '',
            maxLength: el.maxLength ?? -1, readOnly: el.readOnly, invalid: '', autocomplete: el.autocomplete
        };
        fields.set(key, field);
        field.required ||= !!required;
        field.invalid ||= el.validationMessage || (el.getAttribute('aria-invalid') === 'true' ? 'Invalid value' : '');
        if (choice) {
            const option = text(el.parentElement?.querySelector('.application-answer-alternative'));
            field.options.push({label: option || named || el.value, selector, selected: el.checked});
        } else if (tag === 'select') {
            field.options = [...el.options].filter(o => o.value && !o.matches(':disabled')).map(o =>
                ({label: o.label.trim(), value: o.value, selected: o.selected}));
            field.multiple = el.multiple;
        } else {
            field.value = kind === 'file' ? el.files[0]?.name || '' : el.value || '';
        }
    }
    return [...fields.values()].map(f => {
        if (f.options.length) f.value = f.options.filter(o => o.selected).map(o => o.label).join('\n');
        if (f.kind === 'checkbox' && f.options.length === 1) {
            const option = f.options[0];
            if (f.question !== option.label && option.label !== 'on') f.question += ' — ' + option.label;
            f.value = option.selected ? 'Yes' : 'No';
        }
        return f;
    });
}"""


def _enter_answer(form: Locator, field: dict, answer: str) -> str:
    """Enter an approved answer and return the exact display text expected on readback."""
    kind, options = field["kind"], field["options"]
    if kind == "checkbox" and len(options) == 1:
        if answer.casefold() not in ("yes", "no") or (field["required"] and answer.casefold() == "no"):
            raise ValueError("The checkbox needs a valid response before continuing")
        form.locator(options[0]["selector"]).set_checked(answer.casefold() == "yes")
        return answer.capitalize()
    if kind in ("radio", "checkbox", "select"):
        selected = {line.strip().casefold() for line in answer.splitlines() if line.strip()}
        choices = [option for option in options if option["label"].casefold() in selected]
        if not selected or {o["label"].casefold() for o in choices} != selected or len(choices) != len(selected):
            raise ValueError("The approved answer does not uniquely match the available options")
        if len(choices) > 1 and (kind == "radio" or (kind == "select" and not field["multiple"])):
            raise ValueError("Expected one option")
        if kind == "select":
            form.locator(field["selector"]).select_option(value=[o["value"] for o in choices])
        elif kind == "radio":
            form.locator(choices[0]["selector"]).check()
        else:
            for option in options:
                form.locator(option["selector"]).set_checked(option in choices)
        return "\n".join(option["label"] for option in choices)
    if field["value"] != answer:
        if field["readOnly"]:
            raise ValueError("The read-only value differs from the approved answer")
        control = form.locator(field["selector"])
        control.fill(answer)
        control.blur()
    return answer


def fill_application_form(form: Locator, graph, *, company: str, job_id: str, resume_text: str,
                          resume_path: Path | None, answers: list[dict[str, str]]) -> str | None:
    """Return a blocking reason, or None when the currently visible form is complete."""
    accepted: dict[str, str] = {}
    skipped: set[str] = set()
    while True:
        fields = form.evaluate(_READ_FIELDS)
        answers[:] = [{"question": f["question"], "answer": f["value"]} for f in fields
                      if not f["invalid"] and f["value"] == accepted.get(f["key"])]
        for f in fields:
            key, question, kind = f["key"], f["question"], f["kind"]
            if key in accepted:
                if f["value"] != accepted[key] or f["invalid"]:
                    return f"Check {question}: {f['invalid'] or 'the portal changed the answer'}"
                continue
            if key in skipped and not f["required"]:
                continue
            if f["autocomplete"] == "one-time-code" or re.search(r"\b(otp|captcha|verification code|one[- ]time (?:code|password))\b", question, re.I):
                return f"Verification required: {question}"
            if kind == "file" and resume_path and re.search(r"r[eé]sum[eé]|\bcv\b", question, re.I):
                if not f["selector"]:
                    return f"Could not identify the résumé control: {question}"
                form.locator(f["selector"]).set_input_files(resume_path)
                accepted[key] = resume_path.name
                break
            choices = f["options"]
            supported = kind in ("text", "textarea", "email", "tel", "url", "search", "number",
                                 "date", "select", "checkbox", "radio")
            if not supported or not f["selector"] or any(
                not o["selector"] for o in choices if kind in ("radio", "checkbox")
            ):
                if f["required"]:
                    return f"Required field needs input: {question}"
                skipped.add(key)
                continue
            labels = ["Yes", "No"] if kind == "checkbox" and len(choices) == 1 else [o["label"] for o in choices]
            prompt = question + ("\nReturn exact option labels, one per line:\n" + "\n".join(labels) if labels else "")
            if f.get("maxLength", -1) >= 0:
                prompt += f"\nMaximum length: {f['maxLength']} characters."
            answer = graph.invoke({"company": company, "job_id": job_id, "question": prompt,
                                   "resume_text": resume_text}).get("final_answer")
            if not answer:
                if f["required"] or (f["value"] and not (kind == "checkbox" and f["value"] == "No")):
                    return f"Answer needed: {question}"
                skipped.add(key)
                continue
            try:
                accepted[key] = _enter_answer(form, f, answer.strip())
            except ValueError as error:
                return f"Check {question}: {error}"
            except BrowserError:
                return f"Could not enter the approved answer: {question}"
            break
        else:
            return None if answers else "No application fields could be completed."
