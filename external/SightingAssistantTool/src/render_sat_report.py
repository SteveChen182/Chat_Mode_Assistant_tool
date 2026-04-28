import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def _first_present(data: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    for key in keys:
        if key in data:
            return data.get(key)
    return default


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_report_shape(report: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize legacy report layouts into renderer's expected shape.

    Expected shape:
      {
        "meta": {...},
        "sections": {...}
      }
    """
    if not isinstance(report, dict):
        return {"meta": {}, "sections": {}}

    # Some model outputs are wrapped as {"report": {...}}.
    wrapped = report.get("report")
    if isinstance(wrapped, dict):
        report = wrapped

    if isinstance(report.get("sections"), dict):
        sections_in = _as_dict(report.get("sections"))
        if "1.2_description" in sections_in:
            return report

        # Newer compact model output shape:
        # {
        #   "hsd_id": "...",
        #   "report_date": "...",
        #   "sections": {
        #     "section_1_content_extraction": {...},
        #     ...
        #   }
        # }
        s1c = _as_dict(sections_in.get("section_1_content_extraction"))
        s2c = _as_dict(sections_in.get("section_2_issue_classification"))
        s3c = _as_dict(sections_in.get("section_3_attachment_verification"))
        s4c = _as_dict(sections_in.get("section_4_dfd_checklist"))
        s5c = _as_dict(sections_in.get("section_5_triage_troubleshooting"))
        s6c = _as_dict(sections_in.get("section_6_executive_summary"))
        s7c = _as_dict(sections_in.get("section_7_tool_invocation_log"))

        if s1c or s2c or s3c or s4c or s5c or s6c or s7c:
            hsd_id = str(report.get("hsd_id") or "N/A")
            analysis_time = str(report.get("report_date") or datetime.now().strftime("%Y-%m-%d")) + " 00:00:00"

            ptat_data = _as_dict(s5c.get("ptat_analysis"))
            gfxpnp_data = _as_dict(s5c.get("gfxpnp_analysis"))

            def _csv_detailed_summary(block: Dict[str, Any], label: str) -> str:
                if not block:
                    return f"{label}: N/A — no analysis data available."
                parts = [f"{label} Analysis"]
                fname = block.get("file")
                if fname:
                    parts.append(f"File: {fname}.")
                duration = block.get("duration")
                samples = block.get("samples")
                if duration or samples:
                    parts.append(f"Duration: {duration or 'N/A'}, Samples: {samples or 'N/A'}.")
                # Frequency stats
                freq_fields = [
                    ("gfx_freq_min", "GFX Freq Min"),
                    ("gfx_freq_max", "GFX Freq Max"),
                    ("gfx_freq_avg", "GFX Freq Avg"),
                    ("render_freq_min", "Render Freq Min"),
                    ("render_freq_max", "Render Freq Max"),
                    ("render_freq_avg", "Render Freq Avg"),
                ]
                freq_parts = []
                for key, display in freq_fields:
                    val = block.get(key)
                    if val is not None:
                        freq_parts.append(f"{display}: {val}")
                if freq_parts:
                    parts.append(", ".join(freq_parts) + ".")
                finding = block.get("finding")
                if finding:
                    parts.append(f"Finding: {finding}.")
                return " ".join(parts)

            # Build rich 1.3.1: HSD description + comments summary
            hsd_desc_parts = []
            if s1c.get("summary"):
                hsd_desc_parts.append(s1c["summary"])
            if s1c.get("status"):
                hsd_desc_parts.append(f"HSD status: {s1c['status']}.")
            if s1c.get("platform"):
                hsd_desc_parts.append(f"Platform: {s1c['platform']}.")
            if s1c.get("reproducibility"):
                hsd_desc_parts.append(f"Reproducibility: {s1c['reproducibility']}.")
            if s2c.get("reasoning"):
                hsd_desc_parts.append(f"Classification reasoning: {s2c['reasoning']}")
            hsd_desc_analysis = " ".join(hsd_desc_parts) if hsd_desc_parts else "N/A"

            # Build rich 1.3.2: Attachment breakdown
            att_parts = []
            total_att = s3c.get("total_attachments", "N/A")
            att_parts.append(f"Total attachments: {total_att}.")
            for ftype, fcount_key in [("ETL", "etl_files"), ("Log", "log_files"), ("CSV", "csv_files"), ("Trace", "trace_files")]:
                fcount = s3c.get(fcount_key)
                if fcount is not None:
                    att_parts.append(f"{ftype} files: {fcount}.")
            analyzed = s3c.get("analyzed_items", [])
            if analyzed:
                att_parts.append(f"Analyzed: {', '.join(str(a) for a in analyzed)}.")
            not_analyzed = s3c.get("not_analyzed", [])
            if not_analyzed:
                att_parts.append(f"Not analyzed: {', '.join(str(n) for n in not_analyzed)}.")
            attachment_analysis_text = " ".join(att_parts)

            na_msg = "N/A — not analyzed. Use sighting_assistant to analyze."

            checklist_rows = []
            for item in _ensure_list(s4c.get("checklist_items")):
                checklist_label = str(item)
                description = "DFD checklist item — legacy item not evidenced in source data; verify with ETL/log evidence"
                yes_no = "No"

                if isinstance(item, dict):
                    checklist_label = str(
                        item.get("checklist_item")
                        or item.get("item")
                        or item.get("name")
                        or item.get("title")
                        or item
                    )

                    raw_eval = (
                        item.get("yes_no")
                        or item.get("evaluation")
                        or item.get("status")
                        or item.get("result")
                        or item.get("compliant")
                    )
                    raw_evidence = (
                        item.get("evidence")
                        or item.get("evidence_summary")
                        or item.get("evidence_text")
                        or item.get("supporting_evidence")
                        or item.get("etl_evidence")
                        or item.get("log_evidence")
                    )

                    eval_text = str(raw_eval).strip().lower() if raw_eval is not None else ""
                    has_affirmative_eval = raw_eval is True or eval_text in {"yes", "y", "pass", "passed", "true", "compliant"}
                    has_evidence = bool(raw_evidence)

                    if has_affirmative_eval and has_evidence:
                        yes_no = "Yes"
                        description = "DFD checklist item — legacy evaluation evidenced in source data"
                    elif has_affirmative_eval:
                        description = "DFD checklist item — affirmative legacy evaluation present, but no evidence was provided in source data; verify with ETL/log evidence"

                checklist_rows.append({
                    "Checklist Item": checklist_label,
                    "Description": description,
                    "Yes/No": yes_no,
                })
            bkm_guidance = _ensure_list(s4c.get("bkm_guidance"))

            raw_tools_invoked = s7c.get("tools_invoked")
            tools_invoked: List[Any] = raw_tools_invoked if isinstance(raw_tools_invoked, list) else []
            invocation_status = []
            invocation_matrix = []
            for tool_entry in tools_invoked:
                if isinstance(tool_entry, dict):
                    tool_name = str(tool_entry.get("tool", "unknown"))
                    status = str(tool_entry.get("status", "unknown"))
                    invocation_status.append(f"{tool_name}: {status}")
                    invocation_matrix.append(f"{tool_name} | {status}")

            # Build rich triage summary
            triage_parts = []
            if ptat_data:
                triage_parts.append(_csv_detailed_summary(ptat_data, "PTAT"))
            if gfxpnp_data:
                triage_parts.append(_csv_detailed_summary(gfxpnp_data, "GfxPnp"))
            if s6c.get("root_cause_hypothesis"):
                triage_parts.append(f"Root cause hypothesis: {s6c['root_cause_hypothesis']}")
            triage_summary = " | ".join(triage_parts) if triage_parts else "N/A"

            # Build executive summary
            exec_parts = []
            if s6c.get("root_cause_hypothesis"):
                exec_parts.append(s6c["root_cause_hypothesis"])
            recommendations = s6c.get("recommendations", [])
            if recommendations:
                exec_parts.append("Recommendations: " + "; ".join(str(r) for r in recommendations))
            exec_summary = " ".join(exec_parts) if exec_parts else "N/A"

            coerced = {
                "meta": {
                    "id": hsd_id,
                    "title": s1c.get("title", "N/A"),
                    "main_issue": s6c.get("root_cause_hypothesis") or s1c.get("summary") or "N/A",
                    "analysis_time_local": analysis_time,
                },
                "sections": {
                    "1.2_description": s1c.get("summary", "N/A"),
                    "1.3_analysis": {
                        "1.3.1_HSD_Description_and_Comments_Analysis": hsd_desc_analysis,
                        "1.3.2_Attachment_Analysis": attachment_analysis_text,
                        "1.3.3_GOP_Log_Analysis": na_msg,
                        "1.3.4_ETL_Log_Analysis": na_msg,
                        "1.3.5_Burnin_Log_Analysis": na_msg,
                        "1.3.6_Sherlog_Analysis": na_msg,
                        "1.3.7_PTAT_Log_Analysis": {
                            "summary": _csv_detailed_summary(ptat_data, "PTAT"),
                            "plot_paths": ptat_data.get("plot_paths", []),
                        },
                        "1.3.8_GfxPnp_Log_Analysis": {
                            "summary": _csv_detailed_summary(gfxpnp_data, "GfxPnp"),
                            "plot_paths": gfxpnp_data.get("plot_paths", []),
                        },
                    },
                    "1.4_driver_information": {
                        "build_type": s1c.get("build_type", "N/A"),
                        "version": s1c.get("driver_version", "N/A"),
                        "build_date": s1c.get("build_date", "N/A"),
                        "etl_files": f"{s3c.get('etl_files', 0)} ETL files attached" if s3c.get("etl_files") else "None attached",
                        "age_warning": s1c.get("age_warning", "N/A"),
                    },
                    "1.5_pipe_underrun_analysis": {
                        "detected": "Not Detected",
                        "count": 0,
                        "affected_files": "N/A — requires ETL analysis for detection",
                    },
                    "1.6_regression_analysis": {
                        "status": "Unknown" if "rejected" in str(s1c.get("status", "")).lower() else s1c.get("status", "Unknown"),
                        "details": f"HSD status: {s1c.get('status', 'N/A')}. Platform: {s1c.get('platform', 'N/A')}. Reproducibility: {s1c.get('reproducibility', 'N/A')}. No explicit baseline or regression commit identified in the provided context.",
                    },
                    "1.7_rvp_reproducibility": {
                        "status": "Not Specified",
                        "details": f"RVP reproduction not explicitly documented. Issue confirmed on {s1c.get('platform', 'N/A')} with {s1c.get('reproducibility', 'N/A')} reproducibility rate. Form factor: {s1c.get('form_factor', 'N/A')}.",
                    },
                    "1.8_reproduction_steps": s1c.get("reproduction_steps") or [
                        "Refer to HSD bug.to_reproduce field for detailed steps.",
                        f"Platform: {s1c.get('platform', 'N/A')}, OS: {s1c.get('os', 'N/A')}, Driver: {s1c.get('driver_version', 'N/A')}.",
                    ],
                    "1.9_system_config": {
                        "hardware": f"{s1c.get('platform', 'N/A')}, {s1c.get('form_factor', 'N/A')} form factor",
                        "software": f"{s1c.get('os', 'N/A')}, Driver {s1c.get('driver_version', 'N/A')}",
                        "environment": f"Reproducibility: {s1c.get('reproducibility', 'N/A')}",
                    },
                    "2_issue_classification": s2c.get("reasoning") or s2c.get("category") or "N/A",
                    "2_issue_classification_detail": {
                        "category": s2c.get("category", "N/A"),
                        "reason": s2c.get("reasoning", "N/A"),
                        "confidence": s2c.get("confidence", "Medium — based on HSD fields and category classification"),
                    },
                    "3_attachment_verification": attachment_analysis_text,
                    "3_attachment_verification_detail": {
                        "total": s3c.get("total_attachments", "N/A"),
                        "etl_files": s3c.get("etl_files", 0),
                        "log_files": s3c.get("log_files", 0),
                        "csv_files": s3c.get("csv_files", 0),
                        "trace_files": s3c.get("trace_files", 0),
                        "analyzed_items": s3c.get("analyzed_items", []),
                        "not_analyzed": s3c.get("not_analyzed", []),
                    },
                    "4.1_checklist": {
                        "rows": checklist_rows,
                        "bkm_suggestions": bkm_guidance,
                        "compliance": f"{len(checklist_rows)}/{len(checklist_rows)} from RAG" if checklist_rows else "0/0 — checklist retrieval failed",
                        "bkm_source": s2c.get("category", "Internal RAG/DFD context"),
                        "bkm_output": "; ".join(bkm_guidance) if bkm_guidance else "N/A — BKM guidance not retrieved",
                    },
                    "4.2_user_doubt_rag": {
                        "user_query": "N/A - user skipped",
                        "rag_result_summary": "N/A - no query provided",
                        "retrieved_links": [],
                    },
                    "5_triage_troubleshooting_review": triage_summary,
                    "5_triage_troubleshooting_review_detail": {
                        "ptat_analysis": _csv_detailed_summary(ptat_data, "PTAT") if ptat_data else "N/A",
                        "gfxpnp_analysis": _csv_detailed_summary(gfxpnp_data, "GfxPnp") if gfxpnp_data else "N/A",
                        "root_cause_hypothesis": s6c.get("root_cause_hypothesis", "N/A"),
                        "recommended_next_steps": s6c.get("recommendations", []),
                    },
                    "6_executive_summary_recommendations": exec_summary,
                    "6_executive_summary_recommendations_detail": {
                        "technical_summary": s6c.get("root_cause_hypothesis", "N/A"),
                        "actionable_recommendations": s6c.get("recommendations", []),
                        "best_practice": "Archive pass/fail log pairs in one ZIP for comparison.",
                        "priority": "Medium — based on HSD status and reproducibility",
                        "escalation_path": "N/A — review HSD assignment and component ownership",
                        "missing_info": "ETL analysis, GOP analysis, and Sherlog/GDHM analysis were not performed" if not any(
                            s.get("status") == "success" for s in tools_invoked
                            if isinstance(s, dict) and "etl" in str(s.get("tool", "")).lower()
                        ) else "N/A",
                    },
                    "6.5_top_5_similar_hsds": s6c.get("similar_hsds", "N/A - user declined similar HSD search."),
                    "7_tool_status_and_artifacts": {
                        "tool_invocation_status": invocation_status if invocation_status else ["No tool invocation data available in legacy JSON"],
                        "invocation_matrix": invocation_matrix if invocation_matrix else ["N/A"],
                        "call_order_notes": [f"Report generated from legacy JSON format. HSD ID: {hsd_id}."],
                        "output_directory_tree": [f"SAT_{hsd_id}_Output/", f"  SAT_analysis_report.html", f"  sat_report_{hsd_id}.json"],
                        "missing_artifacts": [
                            f"{t}: not generated" for t in ["ETL analysis", "GOP analysis", "Burnin analysis", "Sherlog/GDHM analysis"]
                            if not any(isinstance(ti, dict) and t.split()[0].lower() in str(ti.get("tool", "")).lower() for ti in tools_invoked)
                        ] or ["None — all expected artifacts generated"],
                    },
                },
            }
            return coerced

        return report

    meta = _as_dict(report.get("meta"))
    s1 = _as_dict(report.get("section_1"))
    s2 = _as_dict(report.get("section_2"))
    s3 = _as_dict(report.get("section_3"))
    s4 = _as_dict(report.get("section_4"))
    s5 = _as_dict(report.get("section_5"))
    s6 = _as_dict(report.get("section_6"))
    s7 = _as_dict(report.get("section_7"))

    inv = _as_dict(s1.get("1_3_analysis_inventory"))
    ptat = _first_present(inv, ["1_3_7_ptat_plots", "1.3.7_PTAT_Log_Analysis"], {})
    gfxpnp = _first_present(inv, ["1_3_8_gfxpnp_plots", "1.3.8_GfxPnp_Log_Analysis"], {})

    repro_steps = s1.get("1_8_reproduction_steps")
    if isinstance(repro_steps, dict):
        repro_steps = _first_present(repro_steps, ["steps", "reproduction_steps"], ["N/A"])

    sections: Dict[str, Any] = {
        "1.2_description": _first_present(
            s1,
            ["1_2_description", "1.2_description"],
            "N/A — not analyzed. Use sighting_assistant to analyze.",
        ),
        "1.3_analysis": {
            "1.3.1_HSD_Description_and_Comments_Analysis": _first_present(inv, ["1_3_1_hsd_description_comments", "1_3_1_hsd_description_and_comments", "1.3.1_HSD_Description_and_Comments_Analysis"], "N/A — not analyzed. Use sighting_assistant to analyze."),
            "1.3.2_Attachment_Analysis": _first_present(inv, ["1_3_2_attachment_analysis", "1.3.2_Attachment_Analysis"], "N/A — not analyzed. Use sighting_assistant to analyze."),
            "1.3.3_GOP_Log_Analysis": _first_present(inv, ["1_3_5_gop_logs", "1.3.3_GOP_Log_Analysis"], "N/A — not analyzed. Use sighting_assistant to analyze."),
            "1.3.4_ETL_Log_Analysis": _first_present(inv, ["1_3_4_etl_traces", "1.3.4_ETL_Log_Analysis"], "N/A — not analyzed. Use sighting_assistant to analyze."),
            "1.3.5_Burnin_Log_Analysis": _first_present(inv, ["1_3_1_burnin_log", "1.3.5_Burnin_Log_Analysis"], "N/A — not analyzed. Use sighting_assistant to analyze."),
            "1.3.6_Sherlog_Analysis": _first_present(inv, ["1_3_6_gdhm_ids", "1.3.6_Sherlog_Analysis"], "N/A — not analyzed. Use sighting_assistant to analyze."),
            "1.3.7_PTAT_Log_Analysis": ptat if isinstance(ptat, dict) else {"summary": str(ptat), "plot_paths": []},
            "1.3.8_GfxPnp_Log_Analysis": gfxpnp if isinstance(gfxpnp, dict) else {"summary": str(gfxpnp), "plot_paths": []},
        },
        "1.4_driver_information": _first_present(s1, ["1_4_driver_information", "1.4_driver_information"], {}),
        "1.5_pipe_underrun_analysis": _first_present(s1, ["1_5_pipe_underrun_analysis", "1.5_pipe_underrun_analysis"], {}),
        "1.6_regression_analysis": _first_present(s1, ["1_6_regression_analysis", "1.6_regression_analysis"], {}),
        "1.7_rvp_reproducibility": _first_present(s1, ["1_7_rvp_reproducibility", "1.7_rvp_reproducibility"], {}),
        "1.8_reproduction_steps": repro_steps if isinstance(repro_steps, list) else ["N/A"],
        "1.9_system_config": _first_present(s1, ["1_9_system_config", "1.9_system_config"], {}),
        "2_issue_classification": _first_present(s2, ["summary", "2_issue_classification"], "N/A"),
        "2_issue_classification_detail": _first_present(s2, ["details", "2_issue_classification_detail"], {}),
        "3_attachment_verification": _first_present(s3, ["summary", "3_attachment_verification"], "N/A"),
        "3_attachment_verification_detail": _first_present(s3, ["details", "3_attachment_verification_detail"], {}),
        "4.1_checklist": _first_present(s4, ["4_1_checklist", "checklist", "4.1_checklist"], {}),
        "4.2_user_doubt_rag": _first_present(s4, ["4_2_user_doubt_rag", "user_doubt_rag", "4.2_user_doubt_rag"], {}),
        "5_triage_troubleshooting_review": _first_present(s5, ["summary", "5_triage_troubleshooting_review"], "N/A"),
        "5_triage_troubleshooting_review_detail": _first_present(s5, ["details", "5_triage_troubleshooting_review_detail"], {}),
        "6_executive_summary_recommendations": _first_present(s6, ["summary", "6_executive_summary_recommendations"], "N/A"),
        "6_executive_summary_recommendations_detail": _first_present(s6, ["details", "6_executive_summary_recommendations_detail"], {}),
        "6.5_top_5_similar_hsds": _first_present(s6, ["6_5_top_5_similar_hsds", "6.5_top_5_similar_hsds"], "N/A - user declined similar HSD search."),
        "7_tool_status_and_artifacts": _first_present(s7, ["details", "7_tool_status_and_artifacts"], {}),
    }

    # Fall back to section_1 metadata when top-level meta is sparse.
    if not meta:
        meta = _first_present(s1, ["1_1_hsd_metadata", "1.1_hsd_metadata"], {})

    return {"meta": meta, "sections": sections}


def _parse_json_lenient(raw_text: str) -> Dict[str, Any]:
    """Parse JSON robustly even if model output includes markdown fences."""
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("Structured report JSON file is empty")

    # Remove markdown code fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    # Try direct parse first.
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Structured report JSON must be a top-level object")
        return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: extract the largest JSON object block.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            raise ValueError("Structured report JSON must be a top-level object")
        return parsed

    raise ValueError("Could not parse structured report JSON")


def _escape(value: Any) -> str:
    return html.escape(str(value))


def _ensure_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return [str(value)]


def _render_lines_as_list(lines: Any) -> str:
    items = _ensure_list(lines)
    if not items:
        return "<p>N/A</p>"
    lis = "".join(f"<li>{_escape(item)}</li>" for item in items)
    return f"<ul>{lis}</ul>"


def _render_key_value_table(data: Any) -> str:
    if not isinstance(data, dict) or not data:
        return "<p class=\"na-note\">N/A</p>"

    rows = []
    for key, value in data.items():
        if isinstance(value, list):
            rendered = _render_lines_as_list(value)
        else:
            rendered = _render_section_value(value)
        rows.append(f"<tr><th>{_escape(key)}</th><td>{rendered}</td></tr>")

    return "<table><tbody>" + "".join(rows) + "</tbody></table>"


def _render_checklist_table(checklist: Dict[str, Any]) -> str:
    rows = checklist.get("rows") or []
    if not isinstance(rows, list):
        rows = []

    trs = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = _escape(row.get("Checklist Item", ""))
        desc = _escape(row.get("Description", ""))
        yn = _escape(row.get("Yes/No", "No"))
        cls = "status-ok" if yn.lower() == "yes" else "status-fail"
        trs.append(
            "<tr>"
            f"<td>{item}</td>"
            f"<td>{desc}</td>"
            f"<td class=\"{cls}\">{yn}</td>"
            "</tr>"
        )

    if not trs:
        trs.append(
            "<tr>"
            "<td>RAG retrieval failed</td>"
            "<td>Mandatory checklist could not be retrieved</td>"
            "<td class=\"status-fail\">No</td>"
            "</tr>"
        )

    compliance = _escape(checklist.get("compliance", "N/A"))
    bkm_source = _escape(checklist.get("bkm_source", "N/A"))
    bkm_output = _escape(checklist.get("bkm_output", "N/A"))
    suggestions = _render_lines_as_list(checklist.get("bkm_suggestions"))

    return (
        "<table>"
        "<thead><tr><th>Checklist Item</th><th>Description</th><th>Yes/No</th></tr></thead>"
        f"<tbody>{''.join(trs)}</tbody>"
        "</table>"
        "<div class=\"compliance-summary\">"
        f"<p><strong>Compliance:</strong> {compliance} | <strong>BKM Source:</strong> {bkm_source}</p>"
        f"<p><strong>BKM Output:</strong> {bkm_output}</p>"
        "<div><strong>BKM Suggestions:</strong>"
        f"{suggestions}</div>"
        "</div>"
    )


def _render_plot_images(plot_paths: Any, alt_prefix: str) -> str:
    paths = [p for p in _ensure_list(plot_paths) if str(p).strip()]
    if not paths:
        return "<p>Plot: N/A (not generated)</p>"

    blocks = []
    for idx, path in enumerate(paths, start=1):
        safe_path = _escape(path)
        blocks.append(
            "<div class=\"plot-block\">"
            f"<div><code>{safe_path}</code></div>"
            f"<img src=\"{safe_path}\" alt=\"{_escape(alt_prefix)} Plot {idx}\" />"
            "</div>"
        )
    return "".join(blocks)


def _normalize_plot_src(path: str, output_dir: str) -> str:
    """Return a browser-safe image src for local HTML viewing.

    Rules:
    - If absolute path: return file URI.
    - If path starts with output folder name (duplicated prefix), strip it.
    - Normalize slashes for HTML.
    """
    raw = (path or "").strip()
    if not raw:
        return raw

    # Expand env vars and normalize separators.
    expanded = os.path.expandvars(raw)
    normalized = expanded.replace("\\", "/")

    # Absolute file path -> file URI so browser resolves consistently.
    p = Path(expanded)
    if p.is_absolute():
        try:
            return p.resolve().as_uri()
        except Exception:
            return normalized

    # Remove duplicated output folder prefix for relative paths, e.g.
    # SAT_123_Output/GfxPnp_logs_plots/a.png when HTML is already in SAT_123_Output/
    out_base = Path(output_dir).name.replace("\\", "/") if output_dir else ""
    if out_base:
        prefix = out_base + "/"
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]

    return normalized


def _normalize_plot_paths_in_report(report: Dict[str, Any], output_dir: str) -> None:
    sections = report.get("sections")
    if not isinstance(sections, dict):
        return
    analysis = sections.get("1.3_analysis")
    if not isinstance(analysis, dict):
        return

    for key in ("1.3.7_PTAT_Log_Analysis", "1.3.8_GfxPnp_Log_Analysis"):
        item = analysis.get(key)
        if not isinstance(item, dict):
            continue
        plot_paths = item.get("plot_paths")
        if isinstance(plot_paths, list):
            item["plot_paths"] = [_normalize_plot_src(str(pp), output_dir) for pp in plot_paths]


def _discover_plot_paths(output_dir: str, kind: str) -> List[str]:
    if not output_dir:
        return []

    out = Path(output_dir)
    if not out.exists():
        return []

    patterns: List[str]
    if kind == "ptat":
        patterns = ["PTAT_logs_plots/*.png", "**/*ptat*plot*.png", "**/*ptat*.png"]
    else:
        patterns = ["GfxPnp_logs_plots/*.png", "**/*gfxpnp*plot*.png", "**/*gtmetrics*.png"]

    discovered: List[str] = []
    for pattern in patterns:
        for p in out.glob(pattern):
            if p.is_file():
                discovered.append(_normalize_plot_src(str(p), output_dir))

    # Preserve order while deduping.
    uniq: List[str] = []
    seen = set()
    for p in discovered:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _plot_path_exists(path_str: str) -> bool:
    """Check whether a plot path exists on disk.

    Handles both plain filesystem paths and file:// URIs that may have been
    produced by _normalize_plot_src() — Path('file:///C:/...').exists() always
    returns False, so we strip the scheme before checking.
    """
    s = (path_str or "").strip()
    if not s:
        return False
    if s.startswith("file://"):
        from urllib.parse import unquote
        # file:///C:/... → C:/...   file://host/... → //host/... (UNC)
        local = unquote(s[len("file://"):]).lstrip("/")
        # Restore leading slash on Unix absolute paths
        if not local or (len(local) > 1 and local[1] != ":"):
            local = "/" + local
        return Path(local).exists()
    return Path(os.path.expandvars(s)).exists()


def _inject_missing_plot_paths(report: Dict[str, Any], output_dir: str) -> None:
    sections = report.get("sections")
    if not isinstance(sections, dict):
        return
    analysis = sections.get("1.3_analysis")
    if not isinstance(analysis, dict):
        return

    for key, kind in (
        ("1.3.7_PTAT_Log_Analysis", "ptat"),
        ("1.3.8_GfxPnp_Log_Analysis", "gfxpnp"),
    ):
        item = analysis.get(key)
        if not isinstance(item, dict):
            continue
        plot_paths = item.get("plot_paths")
        # Only skip auto-discovery if at least one path actually exists on disk.
        # NOTE: _normalize_plot_paths_in_report may have converted absolute paths to
        # file:// URIs; Path('file://...').exists() always returns False, so we must
        # strip the URI scheme before checking existence.
        if isinstance(plot_paths, list) and plot_paths:
            valid = [p for p in plot_paths if p and _plot_path_exists(str(p))]
            if valid:
                item["plot_paths"] = valid
                continue
        discovered = _discover_plot_paths(output_dir, kind)
        if discovered:
            item["plot_paths"] = discovered
            summary = str(item.get("summary") or "").strip()
            # Only add auto-discovery note; never overwrite a meaningful summary.
            if summary and "auto-discovered" not in summary.lower() and not summary.startswith("N/A"):
                item["summary"] = summary + " Plot paths auto-discovered from output directory."
            elif not summary or summary.startswith("N/A"):
                item["summary"] = "Plot paths auto-discovered from output directory."


def _render_section_value(value: Any) -> str:
    if value is None:
        return "<p class=\"na-note\">N/A — not analyzed. Use sighting_assistant to analyze.</p>"
    if isinstance(value, dict):
        if "summary" in value:
            return f"<p>{_escape(value.get('summary', ''))}</p>"
        # Render dicts with multiple keys as a key-value table for readability.
        if value:
            return _render_key_value_table(value)
        return "<p class=\"na-note\">N/A</p>"
    if isinstance(value, list):
        return _render_lines_as_list(value)
    text = str(value).strip()
    if not text:
        text = "N/A — not analyzed. Use sighting_assistant to analyze."
    if text.startswith("N/A"):
        return f"<p class=\"na-note\">{_escape(text)}</p>"
    return f"<p>{_escape(text)}</p>"


def render_html(report: Dict[str, Any]) -> str:
    meta = report.get("meta") or {}
    sections = report.get("sections") or {}
    analysis = sections.get("1.3_analysis") or {}

    hsd_id = _escape(meta.get("id", "N/A"))
    title = _escape(meta.get("title", "N/A"))
    main_issue = _escape(meta.get("main_issue", "N/A"))
    analysis_time = _escape(meta.get("analysis_time_local", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    ptat = analysis.get("1.3.7_PTAT_Log_Analysis", {})
    gfxpnp = analysis.get("1.3.8_GfxPnp_Log_Analysis", {})

    section_42 = sections.get("4.2_user_doubt_rag") or {}
    links = _ensure_list(section_42.get("retrieved_links"))
    links_html = "<p>N/A</p>"
    if links:
        links_html = "<ul>" + "".join(f"<li><a href=\"{_escape(link)}\">{_escape(link)}</a></li>" for link in links) + "</ul>"

    section_7 = sections.get("7_tool_status_and_artifacts") or {}

    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>SAT Analysis Report - {hsd_id}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            max-width: 1200px;
            margin: 20px auto;
            padding: 20px;
            background-color: #f5f5f5;
            color: #333;
        }}
        .wrap {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            color: #0066cc;
            border-bottom: 3px solid #0066cc;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        h2 {{
            color: #0066cc;
            border-bottom: 2px solid #0066cc;
            padding-bottom: 8px;
            margin-top: 30px;
            margin-bottom: 15px;
        }}
        h3 {{
            color: #0088cc;
            margin-top: 20px;
            margin-bottom: 10px;
        }}
        h4 {{
            color: #00aacc;
            margin-top: 15px;
            margin-bottom: 8px;
        }}
        .section {{
            background-color: white;
            padding: 20px;
            margin-bottom: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            background-color: white;
        }}
        th {{
            background-color: #0066cc;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: bold;
        }}
        td {{
            padding: 10px 12px;
            border: 1px solid #ddd;
            word-wrap: break-word;
            word-break: break-word;
            overflow-wrap: anywhere;
        }}
        tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        tr:hover {{
            background-color: #f0f0f0;
        }}
        code {{
            background-color: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            word-break: break-all;
        }}
        .status-ok {{
            color: #28a745;
            font-weight: bold;
        }}
        .status-warn {{
            color: #ffc107;
            font-weight: bold;
        }}
        .status-fail {{
            color: #dc3545;
            font-weight: bold;
        }}
        img {{
            max-width: 100%;
            height: auto;
            display: block;
            margin: 15px 0;
            border: 1px solid #ddd;
            border-radius: 4px;
        }}
        ul, ol {{
            margin: 10px 0;
            padding-left: 25px;
        }}
        li {{
            margin: 5px 0;
        }}
        .timestamp {{
            color: #666;
            font-style: italic;
            margin-bottom: 20px;
        }}
        .compliance-summary {{
            background-color: #e8f4f8;
            padding: 15px;
            border-left: 4px solid #0066cc;
            margin: 15px 0;
        }}
        .na-note {{
            color: #666;
            font-style: italic;
        }}
        .gdhm-source {{
            color: #0066cc;
            font-weight: bold;
            font-size: 0.9em;
        }}
        pre {{
            background-color: #f4f4f4;
            padding: 10px;
            border-radius: 4px;
            overflow-x: auto;
            font-size: 0.85em;
            white-space: pre-wrap;
            word-break: break-word;
        }}
        .plot-block {{
            margin: 8px 0 12px;
        }}
    </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"section\">
    <h1>🔍 SAT Analysis Report</h1>
            <p class=\"timestamp\"><strong>Analysis Time:</strong> {analysis_time}</p>
    </div>

    <div class=\"section\">
      <h2>1.1 HSD Metadata</h2>
      <table>
        <tbody>
          <tr><th>ID</th><td>{hsd_id}</td></tr>
          <tr><th>Title</th><td>{title}</td></tr>
          <tr><th>Main Issue</th><td>{main_issue}</td></tr>
          <tr><th>Analysis Time</th><td>{analysis_time}</td></tr>
        </tbody>
      </table>
    </div>

    <div class=\"section\">
      <h2>1.2 Description</h2>
      {_render_section_value(sections.get('1.2_description'))}
    </div>

    <div class=\"section\"><h2>1.3.1 HSD Description and Comments Analysis</h2>{_render_section_value(analysis.get('1.3.1_HSD_Description_and_Comments_Analysis'))}</div>
    <div class=\"section\"><h2>1.3.2 Attachment Analysis</h2>{_render_section_value(analysis.get('1.3.2_Attachment_Analysis'))}</div>
    <div class=\"section\"><h2>1.3.3 GOP Log Analysis</h2>{_render_section_value(analysis.get('1.3.3_GOP_Log_Analysis'))}</div>
    <div class=\"section\"><h2>1.3.4 ETL Log Analysis</h2>{_render_section_value(analysis.get('1.3.4_ETL_Log_Analysis'))}</div>
    <div class=\"section\"><h2>1.3.5 Burnin Log Analysis</h2>{_render_section_value(analysis.get('1.3.5_Burnin_Log_Analysis'))}</div>
    <div class=\"section\"><h2>1.3.6 Sherlog Analysis</h2>{_render_section_value(analysis.get('1.3.6_Sherlog_Analysis'))}</div>

    <div class=\"section\">
      <h2>1.3.7 PTAT Log Analysis</h2>
      {_render_section_value(ptat.get('summary') if isinstance(ptat, dict) else ptat)}
      {_render_plot_images(ptat.get('plot_paths') if isinstance(ptat, dict) else [], 'PTAT')}
    </div>

    <div class=\"section\">
      <h2>1.3.8 GfxPnp Log Analysis</h2>
      {_render_section_value(gfxpnp.get('summary') if isinstance(gfxpnp, dict) else gfxpnp)}
      {_render_plot_images(gfxpnp.get('plot_paths') if isinstance(gfxpnp, dict) else [], 'GfxPnp')}
    </div>

        <div class=\"section\">
            <h2>1.4 Driver Information</h2>
            {_render_key_value_table(sections.get('1.4_driver_information'))}
        </div>

        <div class=\"section\">
            <h2>1.5 Pipe Underrun Analysis</h2>
            {_render_key_value_table(sections.get('1.5_pipe_underrun_analysis'))}
        </div>

        <div class=\"section\">
            <h2>1.6 Regression Analysis</h2>
            {_render_key_value_table(sections.get('1.6_regression_analysis'))}
        </div>

        <div class=\"section\">
            <h2>1.7 RVP Reproducibility</h2>
            {_render_key_value_table(sections.get('1.7_rvp_reproducibility'))}
        </div>

        <div class=\"section\">
            <h2>1.8 Reproduction Steps</h2>
            {_render_lines_as_list(sections.get('1.8_reproduction_steps'))}
        </div>

        <div class=\"section\">
            <h2>1.9 System Config</h2>
            {_render_key_value_table(sections.get('1.9_system_config'))}
        </div>

        <div class=\"section\">
            <h2>🏷️ 2. Issue Classification</h2>
            {_render_section_value(sections.get('2_issue_classification'))}
                        <h3>2.1 Details</h3>
                        {_render_key_value_table(sections.get('2_issue_classification_detail'))}
        </div>

        <div class=\"section\">
            <h2>📎 3. Attachment Verification</h2>
            {_render_section_value(sections.get('3_attachment_verification'))}
                        <h3>3.1 Details</h3>
                        {_render_key_value_table(sections.get('3_attachment_verification_detail'))}
        </div>

    <div class=\"section\">
    <h2>✅ 4.1 DFD Checklist Compliance</h2>
      {_render_checklist_table(sections.get('4.1_checklist') or {})}
    </div>

    <div class=\"section\">
    <h2>📚 4.2 Internal Wiki User Query (RAG)</h2>
      <p><strong>User Query:</strong> {_escape(section_42.get('user_query', 'N/A - user skipped'))}</p>
      <p><strong>RAG Result Summary:</strong> {_escape(section_42.get('rag_result_summary', 'N/A - no query provided'))}</p>
      <div><strong>Retrieved Links:</strong>{links_html}</div>
    </div>

        <div class=\"section\">
            <h2>🛠️ 5. Triage & Troubleshooting Review</h2>
            {_render_section_value(sections.get('5_triage_troubleshooting_review'))}
            <h3>5.1 Details</h3>
            {_render_key_value_table(sections.get('5_triage_troubleshooting_review_detail'))}
        </div>

        <div class=\"section\">
            <h2>📌 6. Executive Summary & Recommendations</h2>
            {_render_section_value(sections.get('6_executive_summary_recommendations'))}
            <h3>6.1 Details</h3>
            {_render_key_value_table(sections.get('6_executive_summary_recommendations_detail'))}
        </div>

    <div class=\"section\">
      <h2>6.5 Top 5 Similar HSDs</h2>
      {_render_section_value(sections.get('6.5_top_5_similar_hsds', 'N/A - user declined similar HSD search.'))}
    </div>

    <div class=\"section\">
    <h2>📋 7 Tool Status and Artifacts</h2>
    <h3>Invocation Status (✅ success / ⚠️ partial / ❌ failure)</h3>
      {_render_lines_as_list(section_7.get('tool_invocation_status'))}
            <h3>Invocation Matrix</h3>
            {_render_lines_as_list(section_7.get('invocation_matrix'))}
      <h3>Call Order Notes</h3>
      {_render_lines_as_list(section_7.get('call_order_notes'))}
      <h3>Output Directory Tree</h3>
      {_render_lines_as_list(section_7.get('output_directory_tree'))}
      <h3>Missing Artifacts</h3>
      {_render_lines_as_list(section_7.get('missing_artifacts'))}
    </div>
  </div>
</body>
</html>
"""


def main() -> int:
    report_json_file = os.environ.get("GNAI_INPUT_REPORT_JSON_FILE", "").strip()
    report_output_file = os.environ.get("GNAI_INPUT_REPORT_OUTPUT_FILE", "").strip()

    if not report_json_file or not report_output_file:
        print(json.dumps({
            "status": "error",
            "message": "Missing required params: report_json_file and report_output_file"
        }, indent=2))
        return 1

    try:
        # Use utf-8-sig so JSON written with BOM is still parsed correctly.
        with open(report_json_file, "r", encoding="utf-8-sig") as f:
            raw = f.read()
        report = _parse_json_lenient(raw)

        report = _coerce_report_shape(report)

        # Always stamp the actual render time — the LLM-generated JSON only has
        # a date (or 00:00:00) because the model doesn't know the real wall-clock time.
        meta = report.setdefault("meta", {})
        meta["analysis_time_local"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        output_dir = os.path.dirname(report_output_file)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        # Normalize plot src paths so local browser can render images reliably.
        _normalize_plot_paths_in_report(report, output_dir)
        _inject_missing_plot_paths(report, output_dir)

        rendered = render_html(report)
        with open(report_output_file, "w", encoding="utf-8") as f:
            f.write(rendered)

        print(json.dumps({
            "status": "success",
            "report_output_file": report_output_file,
            "report_json_file": report_json_file,
            "message": "SAT HTML report rendered successfully"
        }, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "report_output_file": report_output_file,
            "report_json_file": report_json_file,
            "message": f"Failed to render SAT HTML report: {exc}"
        }, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
