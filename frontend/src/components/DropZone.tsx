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
  onFileSelected: (file: File) => void;
  disabled?: boolean;
}

export default function DropZone({ onFileSelected, disabled = false }: DropZoneProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateAndSelect = useCallback(
    (file: File) => {
      setError(null);
      if (!ACCEPTED_TYPES.includes(file.type)) {
        setError(
          `Invalid file type: ${file.type || "unknown"}. Please upload an image (JPEG, PNG, WebP, TIFF, or BMP).`
        );
        return;
      }
      // 20 MB limit (defense in depth; backend validates too)
      if (file.size > 20 * 1024 * 1024) {
        setError("File too large. Maximum size is 20 MB.");
        return;
      }
      onFileSelected(file);
    },
    [onFileSelected]
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
        validateAndSelect(files[0]);
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
        validateAndSelect(files[0]);
      }
      // Reset input so the same file can be selected again
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
        aria-label="Upload invoice image"
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_TYPES.join(",")}
          onChange={handleFileInput}
          style={{ display: "none" }}
          aria-hidden="true"
        />
        <div className="dropzone__content">
          <p className="dropzone__icon">&#128230;</p>
          <p className="dropzone__text">
            {disabled
              ? "Scanning..."
              : "Drag and drop an invoice image here, or click to browse"}
          </p>
          <p className="dropzone__hint">
            Supports JPEG, PNG, WebP, TIFF, BMP (max 20 MB)
          </p>
        </div>
      </div>
      {error && <p className="dropzone__error">{error}</p>}
    </div>
  );
}
