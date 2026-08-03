import { useEffect, useRef, useState } from 'react'

// Variante integree au fil de discussion (voir 05_interface_frontend.md §5.5).
// Props: data = { expiresIn, phoneMasked, attemptsLeft?, error?, locked? }, onSubmit(code), onResend()
export default function OtpModal({ data, onSubmit, onResend }) {
  const [digits, setDigits] = useState(Array(6).fill(''))
  const [secondsLeft, setSecondsLeft] = useState(data.expiresIn)
  const inputsRef = useRef([])

  useEffect(() => {
    if (secondsLeft <= 0 || data.locked) return undefined
    const timer = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000)
    return () => clearInterval(timer)
  }, [secondsLeft, data.locked])

  const expired = secondsLeft <= 0
  const locked = Boolean(data.locked)
  const code = digits.join('')
  const canSubmit = code.length === 6 && !expired && !locked

  function handleChange(index, value) {
    const clean = value.replace(/\D/g, '').slice(-1)
    const next = [...digits]
    next[index] = clean
    setDigits(next)
    if (clean && index < 5) {
      inputsRef.current[index + 1]?.focus()
    }
  }

  function handleKeyDown(index, e) {
    if (e.key === 'Backspace' && !digits[index] && index > 0) {
      inputsRef.current[index - 1]?.focus()
    }
  }

  function handleResend() {
    setDigits(Array(6).fill(''))
    setSecondsLeft(data.expiresIn)
    onResend?.()
  }

  function handleSubmit() {
    if (!canSubmit) return
    onSubmit?.(code)
  }

  return (
    <div className="bg-cih-blue-light rounded-xl p-3 text-sm space-y-2.5 min-w-[240px]">
      <p className="text-gray-600">
        Code envoyé (démonstration) au <span className="font-medium">{data.phoneMasked}</span>
      </p>

      <div className="flex gap-1.5 justify-center">
        {digits.map((d, i) => (
          <input
            key={i}
            ref={(el) => (inputsRef.current[i] = el)}
            value={d}
            disabled={locked || expired}
            onChange={(e) => handleChange(i, e.target.value)}
            onKeyDown={(e) => handleKeyDown(i, e)}
            inputMode="numeric"
            maxLength={1}
            className="w-8 h-9 text-center rounded-lg border border-gray-200 text-sm font-semibold
                       focus:outline-none focus:ring-2 focus:ring-cih-orange disabled:opacity-50"
          />
        ))}
      </div>

      <div className="flex items-center justify-between text-[11px] text-gray-500">
        <span>{expired ? 'Code expiré' : `Expire dans ${secondsLeft}s`}</span>
        {typeof data.attemptsLeft === 'number' && (
          <span>{data.attemptsLeft} tentative(s) restante(s)</span>
        )}
      </div>

      {data.error && <p className="text-[11px] text-red-600">{data.error}</p>}

      {!locked && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="flex-1 bg-cih-orange text-white rounded-lg py-1.5 font-medium hover:bg-cih-orange-dark transition disabled:opacity-50"
          >
            Valider
          </button>
          <button
            onClick={handleResend}
            disabled={!expired}
            className="flex-1 bg-white border border-gray-200 rounded-lg py-1.5 text-gray-600 hover:bg-gray-50 transition disabled:opacity-50"
          >
            Renvoyer
          </button>
        </div>
      )}
      {locked && <p className="text-[11px] text-gray-500">Demande traitée.</p>}
    </div>
  )
}
