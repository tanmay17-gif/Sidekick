import { useState, useEffect, useCallback, useRef } from 'react'
import { Speaker } from '@/lib/voice/synthesis'

interface MCPTool {
  name: string
  title?: string
  description: string
  inputSchema: Record<string, unknown>
  annotations?: {
    readOnlyHint?: boolean
    destructiveHint?: boolean
    idempotentHint?: boolean
    openWorldHint?: boolean
  }
}

interface StepLog {
  timestamp: string
  type: 'voice' | 'agent' | 'mcp-req' | 'mcp-resp' | 'speech'
  text: string
  rawJson?: unknown
}

const PRESET_PROMPTS = [
  { label: 'Run project tests', utterance: 'Alexa, run the project test suite', tool: 'coding.run_tests', args: {} },
  { label: 'Inspect workspace', utterance: 'Alexa, inspect my current repository', tool: 'workspace.inspect', args: {} },
  { label: 'Check git diff', utterance: 'Alexa, show me what files changed', tool: 'vcs.diff', args: {} },
  { label: 'System status', utterance: 'Alexa, what is the system runtime status?', tool: 'system.info', args: {} },
  { label: 'Set volume 50', utterance: 'Alexa, set system volume to 50', tool: 'system.volume', args: { level: 50 } },
  { label: 'Fetch web page', utterance: 'Alexa, check if example.com is reachable', tool: 'web.fetch', args: { url: 'https://example.com' } },
]

const LOG_BG: Record<StepLog['type'], string> = {
  voice: '#022c22',
  agent: '#172554',
  'mcp-req': '#312e81',
  'mcp-resp': '#0f172a',
  speech: '#3b0764',
}

const LOG_ICON: Record<StepLog['type'], string> = {
  voice: '🎤',
  agent: '🤖',
  'mcp-req': '→',
  'mcp-resp': '←',
  speech: '🔊',
}

function summariseJson(type: StepLog['type'], raw: unknown): string | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  if (type === 'mcp-resp') {
    const result = r['result'] as Record<string, unknown> | undefined
    if (!result) return null
    const sc = result['structuredContent'] as Record<string, unknown> | undefined
    if (sc) {
      if (sc['passed'] !== undefined) return sc['passed'] ? '✅ All tests passed' : '❌ Tests had failures'
      if (sc['platform']) return `💻 ${sc['platform']} · ${sc['cpu_count'] ?? '?'} cores`
      if (sc['diff']) return `📝 ${String(sc['diff']).slice(0, 80)}…`
      if (sc['url']) return `🌐 ${sc['url']}`
    }
    const content = result['content'] as Array<Record<string, string>> | undefined
    if (content?.[0]?.text) return content[0].text.slice(0, 120)
  }
  return null
}

function LogEntry({ log }: { log: StepLog }) {
  const [expanded, setExpanded] = useState(false)
  const summary = log.rawJson ? summariseJson(log.type, log.rawJson) : null

  return (
    <div
      style={{
        padding: '8px 12px',
        borderRadius: 6,
        background: LOG_BG[log.type] ?? '#0f172a',
        border: '1px solid rgba(255,255,255,0.08)',
        fontSize: 13,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8', fontSize: 11, marginBottom: 2 }}>
        <span style={{ fontWeight: 600, textTransform: 'uppercase' }}>
          {LOG_ICON[log.type]} {log.type}
        </span>
        <span>{log.timestamp}</span>
      </div>
      <div style={{ color: '#f8fafc', fontWeight: 500 }}>{log.text}</div>
      {summary && (
        <div style={{ marginTop: 4, color: '#7dd3fc', fontSize: 12, fontStyle: 'italic' }}>
          {summary}
        </div>
      )}
      {log.rawJson && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          style={{
            marginTop: 4,
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: '#475569',
            fontSize: 11,
            padding: 0,
            textDecoration: 'underline',
          }}
        >
          {expanded ? '▲ Hide raw JSON' : '▼ View raw JSON'}
        </button>
      )}
      {expanded && log.rawJson && (
        <pre
          style={{
            margin: '4px 0 0',
            padding: 8,
            background: '#020617',
            borderRadius: 4,
            fontSize: 11,
            color: '#38bdf8',
            overflowX: 'auto',
            maxHeight: 200,
          }}
        >
          {JSON.stringify(log.rawJson, null, 2)}
        </pre>
      )}
    </div>
  )
}

export function AlexaPlusSimulator({
  speaker,
  speechEnabled = true,
}: {
  speaker: Speaker
  speechEnabled?: boolean
}) {
  const [tools, setTools] = useState<MCPTool[]>([])
  const [protocolVersion, setProtocolVersion] = useState<string>('2025-11-25')
  const [serverInfo, setServerInfo] = useState<{ name: string; version: string } | null>(null)
  const sessionId = useRef<string>('alexa-sim-' + Math.random().toString(36).slice(2, 9)).current
  const [customInput, setCustomInput] = useState<string>('')
  const [running, setRunning] = useState<boolean>(false)
  const [logs, setLogs] = useState<StepLog[]>([])
  const [activeToolTab, setActiveToolTab] = useState<string | null>(null)

  // Initialize and list tools on mount
  const initMcp = useCallback(async () => {
    try {
      // 1. Initialize
      const initRes = await fetch('/mcp', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Mcp-Session-Id': sessionId,
        },
        body: JSON.stringify({
          jsonrpc: '2.0',
          id: 1,
          method: 'initialize',
          params: { protocolVersion: '2025-11-25' },
        }),
      })
      const initData = await initRes.json()
      if (initData.result) {
        setProtocolVersion(initData.result.protocolVersion || '2025-11-25')
        setServerInfo(initData.result.serverInfo || null)
      }

      // 2. Fetch Tools List
      const toolsRes = await fetch('/mcp', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Mcp-Session-Id': sessionId,
        },
        body: JSON.stringify({
          jsonrpc: '2.0',
          id: 2,
          method: 'tools/list',
          params: {},
        }),
      })
      const toolsData = await toolsRes.json()
      if (toolsData.result?.tools) {
        setTools(toolsData.result.tools)
      }
    } catch (err) {
      console.error('Failed to initialize MCP over HTTP:', err)
    }
  }, [sessionId])

  useEffect(() => {
    void initMcp()
  }, [initMcp])

  const executeAction = async (utterance: string, toolName: string, toolArgs: Record<string, unknown>) => {
    if (running) return
    setRunning(true)
    const newLogs: StepLog[] = []

    const addLog = (type: StepLog['type'], text: string, rawJson?: unknown) => {
      const entry: StepLog = {
        timestamp: new Date().toLocaleTimeString(),
        type,
        text,
        rawJson,
      }
      newLogs.push(entry)
      setLogs((prev) => [entry, ...prev])
    }

    // Step 1: User Voice Utterance
    addLog('voice', `Voice: "${utterance}"`)

    // Step 2: Alexa+ Agent Intent Reasoning
    await new Promise((r) => setTimeout(r, 300))
    addLog('agent', `Alexa+ matched intent -> MCP Tool: ${toolName}`, {
      tool: toolName,
      arguments: toolArgs,
    })

    // Step 3: Streamable HTTP JSON-RPC Request
    const rpcReq = {
      jsonrpc: '2.0',
      id: Date.now(),
      method: 'tools/call',
      params: {
        name: toolName,
        arguments: toolArgs,
      },
    }
    addLog('mcp-req', `POST /mcp (Header: Mcp-Session-Id: ${sessionId})`, rpcReq)

    try {
      const res = await fetch('/mcp', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Mcp-Session-Id': sessionId,
        },
        body: JSON.stringify(rpcReq),
      })

      const rpcResp = await res.json()
      addLog('mcp-resp', `Status ${res.status} OK: Tool Result Received`, rpcResp)

      // Step 4: Spoken summary
      let spoken = `I completed the ${toolName.replace('.', ' ')} request.`
      if (rpcResp.result?.structuredContent) {
        const sc = rpcResp.result.structuredContent
        if (sc.passed !== undefined) {
          spoken = sc.passed ? 'All tests in the project passed successfully.' : 'Tests executed with failures reported.'
        } else if (sc.platform) {
          spoken = `Host system is running ${sc.platform} with ${sc.cpu_count ?? 'multiple'} cores.`
        } else if (sc.action?.state === 'succeeded') {
          spoken = `Action ${toolName} finished successfully.`
        }
      }

      addLog('speech', `Alexa Spoken Response: "${spoken}"`)
      if (speechEnabled) {
        void speaker.speak(spoken)
      }
    } catch (err) {
      addLog('mcp-resp', `Error calling MCP HTTP endpoint: ${String(err)}`)
    } finally {
      setRunning(false)
    }
  }

  const handleCustomSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!customInput.trim()) return

    const trimmed = customInput.trim().toLowerCase()
    let chosenTool = 'system.info'
    let args: Record<string, unknown> = {}

    if (trimmed.includes('test')) {
      chosenTool = 'coding.run_tests'
    } else if (trimmed.includes('diff') || trimmed.includes('git')) {
      chosenTool = 'vcs.diff'
    } else if (trimmed.includes('inspect') || trimmed.includes('workspace') || trimmed.includes('file')) {
      chosenTool = 'workspace.inspect'
    } else if (trimmed.includes('volume')) {
      chosenTool = 'system.volume'
      args = { level: 40 }
    } else if (trimmed.includes('web') || trimmed.includes('fetch')) {
      chosenTool = 'web.fetch'
      args = { url: 'https://example.com' }
    }

    void executeAction(`Alexa, ${customInput.trim()}`, chosenTool, args)
    setCustomInput('')
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', width: '100%', padding: 'var(--space-4)' }}>
      {/* Header banner */}
      <div
        style={{
          background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)',
          border: '1px solid #334155',
          borderRadius: 12,
          padding: 'var(--space-4)',
          marginBottom: 'var(--space-4)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {/* Alexa glowing orb ring */}
          <div
            style={{
              width: 38,
              height: 38,
              borderRadius: '50%',
              background: 'radial-gradient(circle, #38bdf8 0%, #0284c7 70%, #0369a1 100%)',
              boxShadow: running
                ? '0 0 20px #38bdf8, 0 0 40px #0284c7'
                : '0 0 10px rgba(56, 189, 248, 0.4)',
              animation: running ? 'pulse 1.2s infinite' : 'none',
            }}
          />
          <div>
            <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0, color: '#f8fafc' }}>
              Alexa+ Developer Co-Pilot Simulator
            </h2>
            <p style={{ margin: '2px 0 0', fontSize: 13, color: '#94a3b8' }}>
              Interactive agent flow: Voice Request → Alexa+ LLM → Streamable HTTP (spec {protocolVersion}) → Approval Gate
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span
            style={{
              fontSize: 11,
              padding: '3px 8px',
              borderRadius: 6,
              background: '#047857',
              color: '#d1fae5',
              fontWeight: 600,
            }}
          >
            MCP {protocolVersion}
          </span>
          <span
            style={{
              fontSize: 11,
              padding: '3px 8px',
              borderRadius: 6,
              background: '#1e293b',
              color: '#cbd5e1',
              border: '1px solid #475569',
            }}
          >
            {serverInfo ? `${serverInfo.name} v${serverInfo.version}` : 'Connecting...'}
          </span>
        </div>
      </div>

      {/* Preset Action Buttons */}
      <div style={{ marginBottom: 'var(--space-4)' }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8', marginBottom: 8, textTransform: 'uppercase' }}>
          Quick Simulated Voice Prompts
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {PRESET_PROMPTS.map((p) => (
            <button
              key={p.label}
              type="button"
              className="btn btn--sm"
              style={{
                background: '#1e293b',
                color: '#f1f5f9',
                border: '1px solid #334155',
                fontSize: 13,
                cursor: running ? 'not-allowed' : 'pointer',
              }}
              disabled={running}
              onClick={() => void executeAction(p.utterance, p.tool, p.args)}
            >
              🎤 {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Custom Input Form */}
      <form onSubmit={handleCustomSubmit} style={{ display: 'flex', gap: 8, marginBottom: 'var(--space-4)' }}>
        <input
          type="text"
          className="composer__input"
          placeholder='Try asking: "run tests", "show diff", or "system status"...'
          value={customInput}
          onChange={(e) => setCustomInput(e.target.value)}
          disabled={running}
          style={{
            flex: 1,
            background: '#0f172a',
            border: '1px solid #334155',
            borderRadius: 8,
            padding: '10px 14px',
            color: '#f8fafc',
            fontSize: 14,
          }}
        />
        <button
          type="submit"
          className="btn btn--primary"
          disabled={running || !customInput.trim()}
          style={{ whiteSpace: 'nowrap' }}
        >
          {running ? 'Executing...' : 'Speak to Alexa+'}
        </button>
      </form>

      {/* Main Grid: Live Execution Trace + Tools Inspector */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 16 }}>
        {/* Execution Trace */}
        <div
          style={{
            background: '#090d16',
            border: '1px solid #1e293b',
            borderRadius: 10,
            padding: 'var(--space-3)',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              borderBottom: '1px solid #1e293b',
              paddingBottom: 8,
              marginBottom: 10,
            }}
          >
            <span style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0' }}>
              📡 Live Agentic Trace (JSON-RPC Streamable HTTP)
            </span>
            {logs.length > 0 && (
              <button
                type="button"
                className="btn btn--xs btn--ghost"
                onClick={() => setLogs([])}
                style={{ fontSize: 11 }}
              >
                Clear Trace
              </button>
            )}
          </div>

          {logs.length === 0 ? (
            <div style={{ color: '#64748b', fontSize: 13, padding: '16px 0', textAlign: 'center' }}>
              Click any quick prompt above or type a command to see the real-time MCP Streamable HTTP flow.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 420, overflowY: 'auto' }}>
              {logs.map((log, idx) => (
                <LogEntry key={idx} log={log} />
              ))}
            </div>
          )}
        </div>

        {/* MCP Tools Catalog */}
        <div
          style={{
            background: '#090d16',
            border: '1px solid #1e293b',
            borderRadius: 10,
            padding: 'var(--space-3)',
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0', marginBottom: 10 }}>
            🧰 Available MCP Tools ({tools.length} Loaded via tools/list)
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 }}>
            {tools.map((t) => {
              const isReadOnly = t.annotations?.readOnlyHint
              const isDestructive = t.annotations?.destructiveHint
              return (
                <div
                  key={t.name}
                  onClick={() => setActiveToolTab(activeToolTab === t.name ? null : t.name)}
                  style={{
                    background: '#0f172a',
                    border: '1px solid #1e293b',
                    borderRadius: 6,
                    padding: 10,
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <code style={{ fontSize: 12, color: '#38bdf8', fontWeight: 600 }}>{t.name}</code>
                    <span
                      style={{
                        fontSize: 10,
                        padding: '1px 6px',
                        borderRadius: 4,
                        background: isDestructive ? '#991b1b' : isReadOnly ? '#065f46' : '#854d0e',
                        color: '#f8fafc',
                        fontWeight: 600,
                      }}
                    >
                      {isDestructive ? 'HIGH RISK' : isReadOnly ? 'READ ONLY' : 'ACTION'}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: '#94a3b8', lineHeight: 1.3 }}>
                    {t.title ? `${t.title} — ` : ''}{t.description}
                  </div>
                  {activeToolTab === t.name && (
                    <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid #1e293b', fontSize: 11 }}>
                      <div style={{ color: '#cbd5e1', fontWeight: 600 }}>Annotations:</div>
                      <pre style={{ margin: '4px 0', color: '#94a3b8' }}>
                        {JSON.stringify(t.annotations, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
