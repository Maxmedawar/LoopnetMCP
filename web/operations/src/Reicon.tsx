import type { IconFunction } from "reicon";
import { useLayoutEffect, useRef } from "react";

type ReiconProps = {
  icon: IconFunction;
  size?: number;
};

export function Reicon({ icon, size = 18 }: ReiconProps) {
  const host = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const element = icon({ size, color: "currentColor" });
    element.setAttribute("focusable", "false");
    element.setAttribute("aria-hidden", "true");
    host.current?.replaceChildren(element);
    return () => element.remove();
  }, [icon, size]);

  return <span className="control-icon" ref={host} aria-hidden="true" />;
}
