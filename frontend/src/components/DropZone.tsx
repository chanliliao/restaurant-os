import { useState, useCallback, useRef } from "react";
import type { DragEvent, ChangeEvent } from "react";

/** Accepted image MIME types */
const ACCEPTED_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/tiff",
  "image/bmp",
];

interface DropZoneProps {
  onFilesSelected: (files: File[]) => void;
  disabled?: boolean;
}

export default function DropZone({ onFilesSelected, disabled = false }: DropZoneProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queuedCount, setQueuedCount] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateAndSelect = useCallback(
    (fileList: FileList) => {
      setError(null);
      const valid: File[] = [];
      for (let i = 0; i < fileList.length; i++) {
        const file = fileList[i];
        if (!ACCEPTED_TYPES.includes(file.type)) {
          setError(
            `Skipped "${file.name}": invalid type. Accepts JPEG, PNG, WebP, TIFF, BMP.`
          );
          continue;
        }
        if (file.size > 20 * 1024 * 1024) {
          setError(`Skipped "${file.name}": exceeds 20 MB limit.`);
          continue;
        }
        valid.push(file);
      }
      if (valid.length > 0) {
        setQueuedCount(valid.length);
        onFilesSelected(valid);
      }
    },
    [onFilesSelected]
  );

  const handleDragOver = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      if (!disabled) {
        setIsDragOver(true);
      }
    },
    [disabled]
  );

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);
      if (disabled) return;

      const files = e.dataTransfer.files;
      if (files.length > 0) {
        validateAndSelect(files);
      }
    },
    [disabled, validateAndSelect]
  );

  const handleClick = useCallback(() => {
    if (!disabled && fileInputRef.current) {
      fileInputRef.current.click();
    }
  }, [disabled]);

  const handleFileInput = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (files && files.length > 0) {
        validateAndSelect(files);
      }
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    },
    [validateAndSelect]
  );

  const className = [
    "dropzone",
    isDragOver ? "dropzone--drag-over" : "",
    disabled ? "dropzone--disabled" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div>
      <div
        className={className}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        role="button"
        tabIndex={0}
        aria-label="Upload invoice images"
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_TYPES.join(",")}
          multiple
          onChange={handleFileInput}
          style={{ display: "none" }}
          aria-hidden="true"
        />
        <div className="dropzone__content">
          <p className="dropzone__icon">&#128230;</p>
          <p className="dropzone__text">
            {disabled
              ? "Scanning..."
              : "Drag and drop invoice images here, or click to browse"}
          </p>
          <p className="dropzone__hint">
            Supports JPEG, PNG, WebP, TIFF, BMP (max 20 MB) — multiple files allowed
          </p>
          {queuedCount > 1 && !disabled && (
            <p className="dropzone__queued">{queuedCount} files queued</p>
          )}
        </div>
      </div>
      {error && <p className="dropzone__error">{error}</p>}
    </div>
  );
}
