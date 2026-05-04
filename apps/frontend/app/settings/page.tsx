'use client'

import { useAppStore } from '@/stores/app-store'
import { useUiStore } from '@/stores/ui-store'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Bug, RotateCcw } from 'lucide-react'

export default function SettingsPage() {
  const app = useAppStore()
  const ui = useUiStore()

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-8">
      <h1 className="text-2xl font-semibold tracking-tight text-fg">
        Settings
      </h1>
      <p className="mt-1 text-sm text-fg-muted">
        Local app preferences. Backend connection settings live in
        <code className="mx-1 rounded bg-surface-muted px-1 py-0.5 font-mono text-xs">
          .env
        </code>
        on the server.
      </p>

      <div className="mt-6 space-y-4">
        {/* Debug mode */}
        <Card>
          <CardHeader>
            <CardTitle>
              <span className="inline-flex items-center gap-2">
                <Bug size={14} className="text-fg-muted" />
                Debug mode
                {app.debugMode && <Badge tone="warning">ON</Badge>}
              </span>
            </CardTitle>
            <CardDescription>
              Surfaces extra UI affordances for development. No production effect.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              variant={app.debugMode ? 'danger' : 'secondary'}
              onClick={() => {
                app.toggleDebug()
                ui.info(app.debugMode ? 'Debug OFF' : 'Debug ON', 2000)
              }}
            >
              {app.debugMode ? 'Disable debug' : 'Enable debug'}
            </Button>
          </CardContent>
        </Card>

        {/* Reset */}
        <Card>
          <CardHeader>
            <CardTitle>
              <span className="inline-flex items-center gap-2">
                <RotateCcw size={14} className="text-fg-muted" />
                Reset local state
              </span>
            </CardTitle>
            <CardDescription>
              Clears recent campaigns list, sidebar collapse state, debug toggle.
              Does NOT delete any campaigns or simulations.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              variant="danger"
              onClick={() => {
                if (
                  confirm(
                    'Clear local app state (recent campaigns, prefs)?',
                  )
                ) {
                  app.reset()
                  ui.success('Cleared.', 2500)
                }
              }}
            >
              Clear state
            </Button>
          </CardContent>
        </Card>

        {/* About */}
        <Card>
          <CardHeader>
            <CardTitle>About</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
              <Row label="Frontend" value="Next.js · TypeScript · Tailwind" />
              <Row label="Build" value="v3 · Linear" />
              <Row label="Backend" value="Flask Core + FastAPI Sim" />
              <Row label="Gateway" value="Caddy reverse proxy" />
            </dl>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-fg-muted">{label}</dt>
      <dd className="font-mono text-xs text-fg">{value}</dd>
    </>
  )
}
