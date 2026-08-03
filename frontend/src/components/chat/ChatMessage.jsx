import { Bot } from 'lucide-react'
import TransferConfirmationCard from './TransferConfirmationCard.jsx'
import OtpModal from './OtpModal.jsx'
import TransferResult from './TransferResult.jsx'

// Props: message = { id, role, type, content?, data? } - voir 05_interface_frontend.md §5.3/§6.2
// Props additionnelles (wiring Phase 1, sans backend) : onTransferConfirm, onTransferCancel, onOtpSubmit, onOtpResend
export default function ChatMessage({ message, onTransferConfirm, onTransferCancel, onOtpSubmit, onOtpResend }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex items-end gap-2 max-w-[85%] ${isUser ? 'ml-auto flex-row-reverse' : ''}`}>
      {!isUser && (
        <div className="w-6 h-6 rounded-full bg-cih-blue-light flex items-center justify-center shrink-0">
          <Bot className="w-3.5 h-3.5 text-cih-blue" />
        </div>
      )}

      <div
        className={
          isUser
            ? 'bg-cih-orange text-white rounded-2xl rounded-br-sm px-4 py-2 text-sm'
            : 'bg-white border border-gray-100 text-gray-800 rounded-2xl rounded-bl-sm px-4 py-2 text-sm shadow-sm'
        }
      >
        {message.type === 'text' && <span dir="auto">{message.content}</span>}

        {message.type === 'transfer_confirmation' && (
          <TransferConfirmationCard
            data={message.data}
            onConfirm={() => onTransferConfirm?.(message.id)}
            onCancel={() => onTransferCancel?.(message.id)}
          />
        )}

        {message.type === 'otp_request' && (
          <OtpModal
            key={`${message.id}-${message.data.resendCount ?? 0}`}
            data={message.data}
            onSubmit={(code) => onOtpSubmit?.(message.id, code)}
            onResend={() => onOtpResend?.(message.id)}
          />
        )}

        {message.type === 'transfer_result' && <TransferResult data={message.data} />}
      </div>
    </div>
  )
}
