"""Build a reduced persona schema from the MatrAIx source schema.

Run: python3 paper_research/build_product_persona_schema.py
Check: python3 paper_research/build_product_persona_schema.py --check
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/matraix/persona_1m/persona_codes.schema.json"
OUTPUT = ROOT / "data/matraix/persona_1m/projectdut_persona.schema.json"

GROUPS = {
    "activity_and_exposure": {
        "description": "Attributes related to demographics, time, platforms, and attention capacity.",
        "product_relevance": ["agent_activation", "content_exposure"],
        "fields": [
            "age_bracket", "region", "urbanicity", "socioeconomic_band",
            "life_stage", "lstyle_screen_time", "lstyle_social_battery",
            "lstyle_primary_social", "big5_activity_level", "lstyle_work_schedule",
            "lstyle_sleep_schedule", "cog_attention_span",
        ],
    },
    "attention_and_cognition": {
        "description": "Attributes related to personality, cognition, and information-processing tendencies.",
        "product_relevance": ["article_thought", "article_emotion", "product_thought"],
        "fields": [
            "trait_curiosity", "trait_open_mindedness", "trait_prudence",
            "trait_self_regulation", "trait_adaptability", "big5_cautiousness",
            "big5_trust", "big5_excitement_seeking", "bfi2_facet_sociability",
            "bfi2_facet_assertiveness", "bfi2_facet_intellectual_curiosity",
            "bfi2_facet_anxiety", "bfi2_facet_emotional_volatility",
            "risk_tolerance", "decision_style", "cog_skepticism",
            "cog_ambiguity_tolerance", "cog_decision_speed",
            "cog_detail_orientation", "need_for_cognition", "need_for_closure",
        ],
    },
    "purchase_and_preference": {
        "description": "Attributes related to economic motivation, preferences, and shopping tendencies.",
        "product_relevance": ["product_thought", "product_emotion", "purchase_decision", "recommendation"],
        "fields": [
            "economic_motivation", "lstyle_shopping_style", "lstyle_frugality",
            "pref_quality_vs_quantity", "pref_save_vs_spend",
            "pref_novelty_vs_familiarity", "pref_routine_vs_variety",
            "pref_stability_vs_change", "pref_plan_vs_spontaneous",
            "pref_early_vs_late", "att_brand_loyalty", "att_advertising",
            "att_online_reviews", "att_influencers", "att_consumerism",
            "schwartz_value_stimulation", "schwartz_value_security",
            "schwartz_value_hedonism",
        ],
    },
    "social_reaction_and_comment": {
        "description": "Attributes related to communication, emotional expression, and disagreement handling.",
        "product_relevance": ["article_reaction", "comment_generation"],
        "fields": [
            "cog_directness", "cog_politeness", "cog_conflict_approach",
            "cog_storytelling", "cog_verbosity", "cog_precision_of_language",
            "cog_emoji_use", "cog_emotional_expressiveness",
            "cog_empathy_expression", "att_advertising", "att_online_reviews",
        ],
    },
    "cafe_domain": {
        "description": "Attributes related to coffee, caffeine, food, and beverages.",
        "product_relevance": ["content_matching", "article_thought", "product_thought", "recommendation"],
        "fields": [
            "topic_coffee", "lstyle_coffee_ritual", "lstyle_caffeine",
            "topic_tea", "topic_cooking", "topic_baking", "skill_cooking",
            "skill_baking", "ind_food_beverage", "ind_restaurants",
        ],
    },
}

# Chọn một trường đại diện khi schema gốc có nhiều thước đo trùng vai trò.
# Các trường bị loại không phải vô ích; chúng chỉ chưa đưa vào context mặc định.
EXCLUSIONS = {
    "duplicate_constructs": [
        "cog_curiosity", "cog_open_mindedness", "cog_patience",
        "bfi2_domain_open_mindedness", "bfi2_domain_conscientiousness",
        "bfi2_domain_extraversion", "bfi2_domain_negative_emotionality",
        "dominant_trait", "mbti_type",
    ],
    "sensitive_or_product_specific": [
        "health_chronic_condition", "health_mental_health",
        "health_dietary_restriction", "demo_sexual_orientation",
        "demo_ethnicity_broad", "demo_religion_affiliation",
        "political_lean", "religiosity", "neurotype",
    ],
    "not_relevant_to_current_product": [
        "developer_fields", "programming_fields", "political_topics",
        "unrelated_media_and_sports",
    ],
}

FIELD_DESCRIPTIONS = {
    "age_bracket": "Age group.",
    "region": "Broad geographic region.",
    "urbanicity": "Type of residential setting.",
    "socioeconomic_band": "Socioeconomic group.",
    "life_stage": "Life stage.",
    "lstyle_screen_time": "Approximate daily screen-time range.",
    "lstyle_social_battery": "Introversion or extraversion tendency, as represented by the field's categories.",
    "lstyle_primary_social": "Primary social-media platform.",
    "big5_activity_level": "Activity level in the Big Five personality model.",
    "lstyle_work_schedule": "Work-schedule type.",
    "lstyle_sleep_schedule": "Sleep-schedule type.",
    "cog_attention_span": "Tendency to sustain attention.",
    "trait_curiosity": "Curiosity as a character trait.",
    "trait_open_mindedness": "Openness to different viewpoints or options.",
    "trait_prudence": "Prudence as a character trait.",
    "trait_self_regulation": "Tendency to regulate behavior or reactions.",
    "trait_adaptability": "Tendency to adapt to change.",
    "big5_cautiousness": "Cautiousness in the Big Five model.",
    "big5_trust": "General tendency to trust in the Big Five model.",
    "big5_excitement_seeking": "Tendency to seek stimulation or excitement.",
    "bfi2_facet_sociability": "Sociability in the BFI-2 model.",
    "bfi2_facet_assertiveness": "Assertiveness in the BFI-2 model.",
    "bfi2_facet_intellectual_curiosity": "Intellectual curiosity in the BFI-2 model.",
    "bfi2_facet_anxiety": "Anxiety in the BFI-2 model.",
    "bfi2_facet_emotional_volatility": "Emotional volatility in the BFI-2 model.",
    "risk_tolerance": "Tolerance for risk.",
    "decision_style": "Decision-making style.",
    "cog_skepticism": "Tendency to question or verify information.",
    "cog_ambiguity_tolerance": "Tolerance for incomplete or ambiguous information.",
    "cog_decision_speed": "Tendency regarding decision speed.",
    "cog_detail_orientation": "Attention to detail.",
    "need_for_cognition": "Tendency to engage in effortful cognitive processing.",
    "need_for_closure": "Need for a clear or definite conclusion.",
    "economic_motivation": "Economic motivation represented in the persona.",
    "lstyle_shopping_style": "Shopping style.",
    "lstyle_frugality": "Tendency toward saving or spending.",
    "pref_quality_vs_quantity": "Preference for quality or quantity.",
    "pref_save_vs_spend": "Preference for saving or spending.",
    "pref_novelty_vs_familiarity": "Preference for novelty or familiarity.",
    "pref_routine_vs_variety": "Preference for routine or variety.",
    "pref_stability_vs_change": "Preference for stability or change.",
    "pref_plan_vs_spontaneous": "Preference for planning or spontaneity.",
    "pref_early_vs_late": "Tendency to adopt new things early or late.",
    "att_brand_loyalty": "Attitude toward the concept of brand loyalty.",
    "att_advertising": "Attitude toward advertising.",
    "att_online_reviews": "Attitude toward online reviews.",
    "att_influencers": "Attitude toward influencers.",
    "att_consumerism": "Attitude toward consumerism.",
    "schwartz_value_stimulation": "Importance assigned to stimulation or novel experiences.",
    "schwartz_value_security": "Importance assigned to safety and stability.",
    "schwartz_value_hedonism": "Importance assigned to pleasure and enjoyment.",
    "cog_directness": "Directness in communication.",
    "cog_politeness": "Politeness in communication.",
    "cog_conflict_approach": "Tendency for handling disagreement.",
    "cog_storytelling": "Tendency to express ideas through storytelling.",
    "cog_verbosity": "Communication verbosity.",
    "cog_precision_of_language": "Precision in language use.",
    "cog_emoji_use": "Use of emojis or emoticons.",
    "cog_emotional_expressiveness": "Emotional expressiveness.",
    "cog_empathy_expression": "Expression of empathy.",
    "topic_coffee": "Interest in coffee.",
    "lstyle_coffee_ritual": "Typical coffee-use habit or context.",
    "lstyle_caffeine": "Caffeine-use level.",
    "topic_tea": "Interest in tea.",
    "topic_cooking": "Interest in cooking.",
    "topic_baking": "Interest in baking.",
    "skill_cooking": "Cooking skill level.",
    "skill_baking": "Baking skill level.",
    "ind_food_beverage": "Experience in the food and beverage industry.",
    "ind_restaurants": "Experience in the restaurant industry.",
}


def build():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    source_by_id = {column["id"]: column for column in source["columns"]}
    selected = list(dict.fromkeys(
        field for group in GROUPS.values() for field in group["fields"]
    ))
    missing = sorted(set(selected) - set(source_by_id))
    if missing:
        raise AssertionError(f"Missing source fields: {missing}")
    missing_descriptions = sorted(set(selected) - set(FIELD_DESCRIPTIONS))
    if missing_descriptions:
        raise AssertionError(f"Missing descriptions: {missing_descriptions}")

    groups_by_field = {}
    for group_name, group in GROUPS.items():
        for field in group["fields"]:
            groups_by_field.setdefault(field, []).append(group_name)
    columns = []
    for field in selected:
        column = dict(source_by_id[field])
        product_relevance = []
        for group_name in groups_by_field[field]:
            product_relevance.extend(GROUPS[group_name]["product_relevance"])
        column.update({
            "description": FIELD_DESCRIPTIONS[field],
            "selection_groups": groups_by_field[field],
            "product_relevance": list(dict.fromkeys(product_relevance)),
            "limitations": [
                "The value describes one aspect of a persona.",
                "The value does not by itself determine an action or simulation outcome.",
            ],
        })
        columns.append(column)

    output = {
        "format": "projectdut_persona_context_schema",
        "format_version": 2,
        "product": "projectDut2026",
        "purpose": "A reduced persona schema selected from the MatrAIx source schema.",
        "source_schema": "persona_codes.schema.json",
        "source_schema_version": source["format_version"],
        "description_provenance": {
            "status": "draft",
            "language": "en",
            "basis": "Descriptions are derived from id, label, category, and values in the source schema.",
            "scope": "Project-level supplemental descriptions; not official MatrAIx definitions or causal claims.",
        },
        "tag_mapping_status": "draft_agent_flow_v2_input_tags",
        "tag_mapping_file": "../../tags/agent_flow_tag_persona.mapping.v2.json",
        "tag_mapping_note": "The current mapping selects persona context fields for enterprise, article, and product input tags. Thought, emotion, and attention-reason tags are state outputs, not persona mappings. Per-persona context ranking is not implemented.",
        "field_count": len(columns),
        "principles": [
            "Source IDs and enum values are preserved.",
            "Descriptions state the semantic scope of each field.",
            "Product relevance is stored separately from field semantics.",
            "Missing values remain missing; they are not converted to another enum.",
            "The subset does not include brand/product state or event history.",
        ],
        "groups": GROUPS,
        "exclusions": EXCLUSIONS,
        "columns": columns,
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def check():
    output = json.loads(OUTPUT.read_text(encoding="utf-8"))
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert output["field_count"] == len(output["columns"]) == len(set(c["id"] for c in output["columns"]))
    source_by_id = {c["id"]: c for c in source["columns"]}
    assert all(c["id"] in source_by_id for c in output["columns"])
    for column in output["columns"]:
        original = source_by_id[column["id"]]
        assert all(column[key] == original[key] for key in ("id", "label", "category", "values"))
        expected_groups = [
            name for name, group in GROUPS.items() if column["id"] in group["fields"]
        ]
        assert column["selection_groups"] == expected_groups
        assert column["product_relevance"] == list(dict.fromkeys(
            role for name in expected_groups for role in GROUPS[name]["product_relevance"]
        ))
        assert column["description"] == FIELD_DESCRIPTIONS[column["id"]]
        assert "selection_note" not in column
    assert output["format_version"] == 2
    assert output["description_provenance"]["status"] == "draft"
    assert output["description_provenance"]["language"] == "en"
    assert output["tag_mapping_status"] == "draft_agent_flow_v2_input_tags"
    assert (OUTPUT.parent / output["tag_mapping_file"]).is_file()
    assert all(c["description"] and c["limitations"] for c in output["columns"])
    assert all(c["values"] for c in output["columns"])
    assert output["field_count"] == 70
    print(f"PASS: {output['field_count']} selected fields, source enums preserved")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check()
    else:
        build()
        check()
