'use client'

import { use, useEffect, useRef, useState } from 'react'
import { Send, MessageCircle, User, Bot, Sparkles } from 'lucide-react'
import { useAgents, useChatWithAgent } from '@/lib/queries'
import { useUiStore } from '@/stores/ui-store'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/data/skeleton'
import { EmptyState } from '@/components/data/empty-state'
import { ErrorState } from '@/components/data/error-state'
import { cn, truncate } from '@/lib/utils'
import type { AgentSummary, InterviewIntent } from '@/lib/types/backend'

interface ChatTurn {
  id: number
  role: 'user' | 'assistant'
  content: string
  intent?: InterviewIntent
  timestamp: number
}

export default function SimInterviewPage({
  params,
}: {
  params: Promise<{ campaignId: string; simId: string }>
}) {
  const { simId } = use(params)
  const ui = useUiStore()
  const agentsQ = useAgents(simId)
  const chatM = useChatWithAgent()

  const agents = agentsQ.data || []
  const [activeAgentId, setActiveAgentId] = useState<number | null>(null)
  const [filter, setFilter] = useState('')
  const [draft, setDraft] = useState('')
  const [sessions, setSessions] = useState<Record<number, ChatTurn[]>>({})
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const nextIdRef = useRef(1)

  // Auto-pick first agent when list loads
  useEffect(() => {
    if (agents.length > 0 && activeAgentId === null) {
      setActiveAgentId(agents[0].agent_id)
    }
  }, [agents, activeAgentId])

  const activeAgent = agents.find((a) => a.agent_id === activeAgentId)
  const turns = activeAgentId != null ? sessions[activeAgentId] || [] : []

  // Auto-scroll on new turn
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns.length])

  const filteredAgents = agents.filter((a) => {
    if (!filter) return true
    const f = filter.toLowerCase()
    return (
      a.name.toLowerCase().includes(f) ||
      (a.mbti || '').toLowerCase().includes(f) ||
      (a.stance || '').toLowerCase().includes(f)
    )
  })

  async function send() {
    const msg = draft.trim()
    if (!msg || activeAgentId == null) return
    const userTurn: ChatTurn = {
      id: nextIdRef.current++,
      role: 'user',
      content: msg,
      timestamp: Date.now(),
    }
    setSessions((prev) => ({
      ...prev,
      [activeAgentId]: [...(prev[activeAgentId] || []), userTurn],
    }))
    setDraft('')

    try {
      const reply = await chatM.mutateAsync({
        sim_id: simId,
        agent_id: activeAgentId,
        message: msg,
        history: (sessions[activeAgentId] || []).map((t) => ({
          role: t.role,
          content: t.content,
        })),
      })
      const assistantTurn: ChatTurn = {
        id: nextIdRef.current++,
        role: 'assistant',
        content: reply.response,
        intent: reply.intent,
        timestamp: Date.now(),
      }
      setSessions((prev) => ({
        ...prev,
        [activeAgentId]: [...(prev[activeAgentId] || []), assistantTurn],
      }))
    } catch (e) {
      ui.error('Chat failed: ' + (e as Error).message)
    }
  }

  if (agentsQ.isError) {
    return (
      <ErrorState
        title="Could not load agents"
        description={(agentsQ.error as Error).message}
        onRetry={() => agentsQ.refetch()}
      />
    )
  }

  return (
    <div className="grid h-[calc(100vh-220px)] grid-cols-[280px_1fr_280px] gap-4 max-xl:grid-cols-[260px_1fr] max-md:grid-cols-1">
      {/* Agent list */}
      <Card className="flex min-h-0 flex-col">
        <div className="border-b border-border p-2.5">
          <Input
            placeholder="Filter agents…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
          {agentsQ.isLoading ? (
            <div className="space-y-1.5 p-2">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          ) : filteredAgents.length === 0 ? (
            <p className="px-3 py-4 text-xs text-fg-muted">
              {agents.length === 0
                ? 'No agents yet — run the sim first.'
                : 'No matches.'}
            </p>
          ) : (
            <ul className="space-y-0.5">
              {filteredAgents.map((a) => (
                <li key={a.agent_id}>
                  <button
                    onClick={() => setActiveAgentId(a.agent_id)}
                    className={cn(
                      'flex w-full items-start gap-2.5 rounded-md px-2 py-2 text-left transition-colors',
                      a.agent_id === activeAgentId
                        ? 'bg-surface-muted'
                        : 'hover:bg-surface-subtle',
                    )}
                  >
                    <Avatar agent={a} active={a.agent_id === activeAgentId} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-fg">
                        {a.name}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5 text-2xs text-fg-muted">
                        {a.mbti && <span className="font-mono">{a.mbti}</span>}
                        {a.stance && (
                          <span className="truncate">· {a.stance}</span>
                        )}
                      </div>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      {/* Chat pane */}
      <Card className="flex min-h-0 flex-col">
        {activeAgent ? (
          <>
            <CardHeader className="border-b border-border pb-3">
              <div className="flex items-center gap-2.5">
                <Avatar agent={activeAgent} active />
                <div className="min-w-0 flex-1">
                  <CardTitle className="text-md">{activeAgent.name}</CardTitle>
                  <p className="mt-0.5 text-xs text-fg-muted">
                    {[activeAgent.mbti, activeAgent.stance]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                </div>
              </div>
            </CardHeader>

            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {turns.length === 0 ? (
                <EmptyState
                  icon={MessageCircle}
                  title="Start the conversation"
                  description={`Ask ${activeAgent.name} about their experience in the sim — what they posted, why they liked someone, how they reacted to a crisis.`}
                  className="border-0 bg-transparent"
                />
              ) : (
                <ul className="flex flex-col gap-3">
                  {turns.map((t) => (
                    <li
                      key={t.id}
                      className={cn(
                        'flex gap-2.5',
                        t.role === 'user' ? 'flex-row-reverse' : 'flex-row',
                      )}
                    >
                      <div
                        className={cn(
                          'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs',
                          t.role === 'user'
                            ? 'bg-fg text-surface'
                            : 'bg-brand-50 text-brand-600',
                        )}
                      >
                        {t.role === 'user' ? <User size={13} /> : <Bot size={13} />}
                      </div>
                      <div
                        className={cn(
                          'min-w-0 max-w-[80%] rounded-lg px-3 py-2 text-sm leading-snug',
                          t.role === 'user'
                            ? 'bg-fg text-surface'
                            : 'border border-border bg-surface-subtle text-fg',
                        )}
                      >
                        <p className="whitespace-pre-wrap">{t.content}</p>
                        {t.intent && (
                          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-2xs text-fg-faint">
                            <Badge tone="brand" className="gap-1">
                              <Sparkles size={9} />
                              {t.intent.classified_as}
                            </Badge>
                            {t.intent.context_blocks_loaded.slice(0, 3).map((b) => (
                              <span
                                key={b}
                                className="font-mono text-2xs text-fg-faint"
                              >
                                {b}
                              </span>
                            ))}
                            {t.intent.model_used && (
                              <span className="ml-auto font-mono text-2xs">
                                {truncate(t.intent.model_used, 18)}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </li>
                  ))}
                  {chatM.isPending && (
                    <li className="flex gap-2.5">
                      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600">
                        <Bot size={13} />
                      </div>
                      <div className="rounded-lg border border-border bg-surface-subtle px-3 py-2 text-sm">
                        <span className="inline-flex gap-1">
                          <Dot delay={0} />
                          <Dot delay={150} />
                          <Dot delay={300} />
                        </span>
                      </div>
                    </li>
                  )}
                  <div ref={messagesEndRef} />
                </ul>
              )}
            </div>

            <div className="border-t border-border p-3">
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  send()
                }}
                className="flex gap-2"
              >
                <Input
                  placeholder={`Message ${activeAgent.name}…`}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  disabled={chatM.isPending}
                  className="flex-1"
                />
                <Button
                  type="submit"
                  variant="primary"
                  loading={chatM.isPending}
                  disabled={!draft.trim()}
                >
                  <Send size={13} />
                  Send
                </Button>
              </form>
            </div>
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center p-8">
            <EmptyState
              icon={MessageCircle}
              title="Pick an agent"
              description="Choose someone from the list to start a conversation."
              className="border-0 bg-transparent"
            />
          </div>
        )}
      </Card>

      {/* Detail pane — hidden on smaller screens */}
      <Card className="flex min-h-0 flex-col max-xl:hidden">
        <CardHeader>
          <CardTitle className="text-sm">Agent profile</CardTitle>
        </CardHeader>
        <CardContent className="flex-1 overflow-y-auto">
          {activeAgent ? (
            <div className="space-y-3 text-sm">
              {activeAgent.persona_short && (
                <div>
                  <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-fg-faint">
                    Persona
                  </div>
                  <p className="leading-snug text-fg-muted">
                    {activeAgent.persona_short}
                  </p>
                </div>
              )}
              {activeAgent.bio && (
                <div>
                  <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-fg-faint">
                    Bio
                  </div>
                  <p className="leading-snug text-fg-muted">{activeAgent.bio}</p>
                </div>
              )}

              <div className="space-y-1.5 border-t border-border pt-3 text-sm">
                <Row label="Posts">{activeAgent.total_posts ?? '—'}</Row>
                <Row label="Comments">{activeAgent.total_comments ?? '—'}</Row>
                <Row label="Likes given">
                  {activeAgent.total_likes_given ?? '—'}
                </Row>
                <Row label="Engagement received">
                  {activeAgent.total_engagement_received ?? '—'}
                </Row>
              </div>
            </div>
          ) : (
            <p className="text-xs text-fg-muted">Pick an agent to see profile.</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-fg-muted">{label}</span>
      <span className="font-mono text-xs text-fg">{children}</span>
    </div>
  )
}

function Avatar({ agent, active }: { agent: AgentSummary; active?: boolean }) {
  const letter = (agent.avatar_letter || agent.name[0] || 'A').toUpperCase()
  return (
    <div
      className={cn(
        'flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-medium',
        active
          ? 'bg-brand-500 text-white'
          : 'bg-surface-muted text-fg-muted',
      )}
    >
      {letter}
    </div>
  )
}

function Dot({ delay }: { delay: number }) {
  return (
    <span
      className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-fg-faint"
      style={{ animationDelay: `${delay}ms` }}
    />
  )
}
