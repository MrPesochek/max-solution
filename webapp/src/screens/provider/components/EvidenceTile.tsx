import { useRef } from 'react';
import { strings } from '../../../strings/ru';
import './evidence.css';

export interface EvidenceFile {
  name: string;
  size: number;
  type: string;
}

function badge(file: EvidenceFile): string {
  if (file.type === 'application/pdf' || /\.pdf$/i.test(file.name)) return 'PDF';
  if (file.type.startsWith('image/')) return 'IMG';
  return 'DOC';
}

function UploadIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M12 17v-6M9 14l3-3 3 3"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function EvidenceTile({
  files,
  onPick,
  onRemove,
  inputLabel,
  title = strings.orgForm.docTitle,
  hint = strings.orgForm.docHint,
  busy,
  disabled,
}: {
  files: EvidenceFile[];
  onPick: (file: File) => void;
  onRemove?: (index: number) => void;
  inputLabel: string;
  title?: string;
  hint?: string;
  busy?: string | null;
  disabled?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="pv-evidence">
      {files.map((file, index) => (
        <div key={`${file.name}-${index}`} className="pv-evidence__file">
          <span className="pv-evidence__badge" aria-hidden="true">
            {badge(file)}
          </span>
          <span className="pv-evidence__main">
            <span className="pv-evidence__title">{file.name}</span>
            <span className="pv-evidence__hint">
              {strings.orgForm.fileSize(file.size)} · {strings.orgForm.docOperatorOnly}
            </span>
          </span>
          {onRemove && (
            <button
              type="button"
              className="pv-evidence__remove"
              aria-label={`${strings.orgForm.docRemove}: ${file.name}`}
              onClick={() => onRemove(index)}
            >
              {strings.orgForm.docRemove}
            </button>
          )}
        </div>
      ))}
      <button
        type="button"
        className="pv-evidence__pick"
        disabled={disabled || Boolean(busy)}
        aria-busy={busy ? true : undefined}
        onClick={() => input.current?.click()}
      >
        <span className="pv-evidence__icon">
          <UploadIcon />
        </span>
        <span className="pv-evidence__main">
          <span className="pv-evidence__title">{title}</span>
          <span className="pv-evidence__hint">{busy ?? hint}</span>
        </span>
      </button>
      <input
        ref={input}
        type="file"
        accept="image/*,application/pdf"
        hidden
        aria-label={inputLabel}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (file) onPick(file);
        }}
      />
    </div>
  );
}
