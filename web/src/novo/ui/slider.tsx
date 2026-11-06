import * as React from 'react'
import { cn } from 'cn'
import { Slider as SliderPrimitive } from 'radix-ui'

// shadcn/ui, com o `aria-label` no polegar (é ele que tem o papel de slider): trilho em `controle`, faixa em `foco`; o anel de foco é o contorno global do index.css.
export function Slider({ className, defaultValue, value, min = 0, max = 100, 'aria-label': rotulo, ...props }: React.ComponentProps<typeof SliderPrimitive.Root>) {
  const valores = React.useMemo(() => (Array.isArray(value) ? value : Array.isArray(defaultValue) ? defaultValue : [min, max]), [value, defaultValue, min, max])
  return (
    <SliderPrimitive.Root
      data-slot="slider"
      defaultValue={defaultValue}
      value={value}
      min={min}
      max={max}
      className={cn('relative flex w-full touch-none items-center select-none data-disabled:opacity-50', className)}
      {...props}
    >
      <SliderPrimitive.Track data-slot="slider-track" className="relative h-1 w-full grow overflow-hidden rounded-full bg-secondary">
        <SliderPrimitive.Range data-slot="slider-range" className="absolute h-full bg-primary" />
      </SliderPrimitive.Track>
      {valores.map((_, i) => (
        <SliderPrimitive.Thumb
          data-slot="slider-thumb"
          key={i}
          aria-label={rotulo}
          className="relative block size-3 shrink-0 rounded-full border border-ring bg-foreground after:absolute after:-inset-2 disabled:pointer-events-none"
        />
      ))}
    </SliderPrimitive.Root>
  )
}
