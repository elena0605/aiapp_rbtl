'use client'

import { useState, FormEvent } from 'react'
import { Lock, User, LogIn } from 'lucide-react'

const TESTER_ACCOUNTS = ['bojan', 'roel', 'famke', 'scarlett']
const SHARED_PASSWORD = 'Rbtlgraph2025!'

interface LoginProps {
  onLogin: (username: string) => void
}

export default function Login({ onLogin }: LoginProps) {
  const [selectedAccount, setSelectedAccount] = useState<string>('')
  const [password, setPassword] = useState<string>('')
  const [error, setError] = useState<string>('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')

    if (!selectedAccount) {
      setError('Please select a tester account')
      return
    }

    if (!password) {
      setError('Please enter the password')
      return
    }

    setIsSubmitting(true)

    await new Promise(resolve => setTimeout(resolve, 300))

    if (password === SHARED_PASSWORD) {
      onLogin(selectedAccount)
    } else {
      setError('Invalid password. Please try again.')
      setPassword('')
      setIsSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-indigo-50/30 to-slate-100 flex items-center justify-center p-4">
      <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-xl shadow-indigo-100/40 ring-1 ring-gray-100 p-8 md:p-10 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-indigo-500 to-violet-500 rounded-2xl mb-5 shadow-lg shadow-indigo-200/60">
            <Lock className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight mb-1">
            <span className="bg-gradient-to-r from-indigo-600 to-violet-600 bg-clip-text text-transparent">Graph</span>RAG
          </h1>
          <p className="text-sm text-gray-400">Please sign in to continue</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label htmlFor="account" className="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
              Tester Account
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                <User className="h-4 w-4 text-gray-400" />
              </div>
              <select
                id="account"
                value={selectedAccount}
                onChange={(e) => {
                  setSelectedAccount(e.target.value)
                  setError('')
                }}
                className="block w-full pl-10 pr-3 py-2.5 border border-gray-200 rounded-xl shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 bg-gray-50/50 text-gray-900 text-sm transition-all"
                disabled={isSubmitting}
              >
                <option value="">Select a tester account</option>
                {TESTER_ACCOUNTS.map((account) => (
                  <option key={account} value={account}>
                    {account.charAt(0).toUpperCase() + account.slice(1)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label htmlFor="password" className="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
              Password
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                <Lock className="h-4 w-4 text-gray-400" />
              </div>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value)
                  setError('')
                }}
                className="block w-full pl-10 pr-3 py-2.5 border border-gray-200 rounded-xl shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 bg-gray-50/50 text-gray-900 text-sm placeholder-gray-400 transition-all"
                placeholder="Enter password"
                disabled={isSubmitting}
                autoComplete="current-password"
              />
            </div>
          </div>

          {error && (
            <div className="bg-rose-50 border border-rose-100 rounded-xl px-4 py-3">
              <p className="text-sm text-rose-600">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={isSubmitting || !selectedAccount || !password}
            className="w-full flex items-center justify-center gap-2 bg-indigo-500 text-white py-2.5 px-4 rounded-xl font-medium text-sm hover:bg-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-300 focus:ring-offset-2 disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed transition-all shadow-sm hover:shadow-md hover:shadow-indigo-200/50"
          >
            {isSubmitting ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <span>Signing in&hellip;</span>
              </>
            ) : (
              <>
                <LogIn className="w-4 h-4" />
                <span>Sign In</span>
              </>
            )}
          </button>
        </form>

        <div className="mt-6 text-center">
          <p className="text-[11px] text-gray-400">
            Shared password for all tester accounts
          </p>
        </div>
      </div>
    </div>
  )
}
