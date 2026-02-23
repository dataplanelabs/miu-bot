"""Consolidation prompt templates for BASB memory system."""

DAILY_CONSOLIDATION_PROMPT = """You are a memory consolidation agent for {workspace_name}.

Today's date: {date}
Messages to process: {message_count}

## Current Active Memories
{current_memories}

## Today's Conversations
{conversations}

## Instructions
Analyze all conversations and return a JSON object:

{{
  "daily_summary": "2-3 sentence summary of what happened today",
  "key_topics": ["topic1", "topic2"],
  "decisions_made": ["decision1"],
  "action_items": ["item1"],
  "emotional_tone": "neutral|positive|negative|mixed",
  "new_facts": [
    {{"content": "fact text", "category": "preference|fact|decision", "priority": 0}}
  ],
  "updated_facts": [
    {{"memory_id": "existing-id", "new_content": "updated text"}}
  ],
  "stale_facts": ["memory-id-to-demote"]
}}

Rules:
- Extract DURABLE facts only (preferences, decisions, project context)
- Ignore ephemeral info (greetings, timestamps, debug output)
- Priority 0 = low importance, 5 = critical
- updated_facts: only if existing memory needs correction
- stale_facts: memories contradicted or superseded by today's info

Respond with ONLY valid JSON."""


WEEKLY_CONSOLIDATION_PROMPT = """You are consolidating a week of knowledge for {workspace_name}.

Week: {week_start} to {week_end}

## Daily Notes This Week
{daily_notes}

## Current Active Memories
{active_memories}

## Instructions
Analyze the week's activity and return JSON:

{{
  "weekly_insight": "3-5 sentence summary of the week's themes and progress",
  "patterns": ["recurring pattern 1", "pattern 2"],
  "promote_to_reference": [
    {{"content": "stable knowledge to promote", "category": "preference|fact|decision"}}
  ],
  "demote_from_active": ["memory-id-1", "memory-id-2"],
  "updated_active": [
    {{"memory_id": "id", "new_content": "corrected or refined content"}}
  ]
}}

Rules:
- promote_to_reference: knowledge that appeared 3+ times or is clearly permanent
- demote_from_active: memories that are no longer relevant this week
- updated_active: memories that need correction based on this week's info
- weekly_insight should capture TRENDS, not just list events

Respond with ONLY valid JSON."""


MONTHLY_CONSOLIDATION_PROMPT = """You are performing monthly deep consolidation for {workspace_name}.

Month: {month}

## Weekly Insights
{weekly_insights}

## Current Reference Memories
{reference_memories}

## Instructions
Analyze the month's knowledge and return JSON:

{{
  "monthly_summary": "5-10 sentence comprehensive summary of the month",
  "trends": ["trend 1", "trend 2"],
  "archive_from_reference": ["memory-id-1"],
  "prune_contradictions": [
    {{"memory_id": "id", "reason": "contradicted by newer info"}}
  ],
  "key_knowledge": [
    {{"content": "distilled knowledge", "category": "domain|preference|project"}}
  ]
}}

Rules:
- archive_from_reference: stable knowledge that hasn't changed in 30+ days
- prune_contradictions: memories that conflict with more recent information
- key_knowledge: most important distilled facts from the month
- monthly_summary captures evolution and growth, not just events

Respond with ONLY valid JSON."""
