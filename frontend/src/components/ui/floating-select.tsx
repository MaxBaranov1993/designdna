import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "../../lib/utils";

export type FloatingSelectOption = { value: string; label: string };

type FloatingSelectProps = {
  value: string;
  options: FloatingSelectOption[];
  onChange: (value: string) => void;
  className?: string;
  ariaLabel?: string;
};

type MenuPosition = { left: number; top: number; width: number; maxHeight: number };

/** A canvas-safe select. Native option popups can be clipped by React Flow's transform. */
export function FloatingSelect({ value, options, onChange, className, ariaLabel }: FloatingSelectProps) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<MenuPosition | null>(null);

  const selected = options.find((option) => option.value === value) || options[0];

  const updatePosition = () => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const estimatedHeight = Math.min(240, Math.max(36, options.length * 36 + 8));
    const roomBelow = window.innerHeight - rect.bottom - 8;
    const roomAbove = rect.top - 8;
    const openUp = roomBelow < Math.min(estimatedHeight, 240) && roomAbove > roomBelow;
    const maxHeight = Math.max(120, Math.min(240, openUp ? roomAbove : roomBelow));
    setPosition({
      left: rect.left,
      top: openUp ? Math.max(8, rect.top - Math.min(estimatedHeight, maxHeight)) : rect.bottom + 5,
      width: Math.max(rect.width, 120),
      maxHeight,
    });
  };

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
    const onViewportChange = () => updatePosition();
    window.addEventListener("resize", onViewportChange);
    window.addEventListener("scroll", onViewportChange, true);
    return () => {
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
    };
  }, [open, options.length]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={cn("floating-select-trigger", className)}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={() => setOpen((current) => !current)}
      >
        <span>{selected?.label || value}</span>
        <span className="floating-select-chevron" aria-hidden="true">⌄</span>
      </button>
      {open && position
        ? createPortal(
            <div
              ref={menuRef}
              className="floating-select-menu"
              role="listbox"
              aria-label={ariaLabel}
              style={{ left: position.left, top: position.top, width: position.width, maxHeight: position.maxHeight }}
              onPointerDown={(event) => event.stopPropagation()}
            >
              {options.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="option"
                  aria-selected={option.value === value}
                  className={cn("floating-select-option", option.value === value && "selected")}
                  onClick={() => {
                    onChange(option.value);
                    setOpen(false);
                    triggerRef.current?.focus();
                  }}
                >
                  {option.label}
                </button>
              ))}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
