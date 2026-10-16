import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { StudioApp } from './studio/StudioApp'
import './index.css'

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  state = { hasError: false, error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError && this.state.error) {
      return (
        <div style={{ padding: 24, fontFamily: 'system-ui', maxWidth: 560 }}>
          <h1 style={{ marginBottom: 8 }}>Something went wrong</h1>
          <pre style={{ fontSize: 12, overflow: 'auto', marginBottom: 16 }}>
            {this.state.error.message}
          </pre>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{ padding: '8px 16px', cursor: 'pointer' }}
          >
            Reload page
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      {window.location.pathname.startsWith('/studio') ? <StudioApp /> : <App />}
    </ErrorBoundary>
  </React.StrictMode>,
)
