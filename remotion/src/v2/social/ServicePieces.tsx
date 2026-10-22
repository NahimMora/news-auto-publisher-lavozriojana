// Contenido de las placas de servicio, compartido por la historia (StoryV2,
// kinds "payments" y "quake") y el post 1080×1350 (ServiceCardV2):
//
//   payments  cronograma de pagos de Hacienda: día de cobro, concepto y
//             organismos (agrupados por banco cuando la fuente los separa).
//   quake     sismo sentido en La Rioja (INPRES): magnitud, hora, epicentro,
//             profundidad y localidades donde se sintió con su intensidad.
//
// Todos los textos llegan armados desde Python con lo que publica la fuente.
import React from "react";
import { z } from "zod";
import { fit } from "../fit";
import { C, V2_FONT_SANS, V2_FONT_SERIF, rgba } from "../tokens";
import { caps, display, serif } from "./chrome";

export const PaymentGroup = z.object({ title: z.string().default(""), items: z.array(z.string()) });
export const FeltPlace = z.object({ place: z.string(), intensity: z.string() });

export const ServicePiecesSchema = {
  headline: z.string().default(""),
  subhead: z.string().default(""),
  groups: z.array(PaymentGroup).default([]),
  magnitude: z.string().default(""),
  epicenter: z.string().default(""),
  depth: z.string().default(""),
  felt: z.array(FeltPlace).default([]),
};

type Group = z.infer<typeof PaymentGroup>;

interface Layout {
  size: number;
  columns: number;
  groups: { title: string; items: string[][] }[];
  hidden: number;
}

const ITEM_GAP = 0.42;
const GROUP_GAP = 1.1;

// Busca el mayor tamaño (y 1 o 2 columnas) con el que todos los organismos
// entran en `height`. Si ni con el mínimo entran, corta y avisa cuántos faltan.
function layoutGroups(groups: Group[], width: number, height: number): Layout {
  const total = groups.reduce((n, g) => n + g.items.length, 0);
  for (let size = 40; size >= 22; size -= 2) {
    for (const columns of total > 8 ? [2, 1] : [1, 2]) {
      const colW = columns === 2 ? (width - 48) / 2 : width;
      const wrapped = groups.map((g) => ({
        title: g.title,
        items: g.items.map((t) => fit({ text: t, maxWidth: colW - size * 0.9, maxHeight: 9999, min: size, max: size, weight: 700, lh: 1.12, stretch: "semi-condensed" }).lines),
      }));
      let used = 0;
      for (const g of wrapped) {
        const lines = g.items.map((l) => l.length);
        const perCol = columns === 2 ? splitColumns(lines) : [lines];
        const tallest = Math.max(...perCol.map((col) => col.reduce((h, n) => h + n * size * 1.12 + size * ITEM_GAP, 0)));
        used += (g.title ? size * 1.6 : 0) + tallest + size * GROUP_GAP;
      }
      if (used <= height) return { size, columns, groups: wrapped, hidden: 0 };
    }
  }
  // Mínimo: corta la última parte y lo dice con la cuenta exacta.
  const size = 22;
  const colW = (width - 48) / 2;
  const capacity = Math.floor(height / (size * (1.12 + ITEM_GAP))) * 2 - 2;
  let shown = 0;
  const groupsOut = groups.map((g) => {
    const items = g.items.slice(0, Math.max(0, capacity - shown));
    shown += items.length;
    return {
      title: g.title,
      items: items.map((t) => fit({ text: t, maxWidth: colW - size * 0.9, maxHeight: 9999, min: size, max: size, weight: 700, lh: 1.12, maxLines: 1 }).lines),
    };
  });
  return { size, columns: 2, groups: groupsOut.filter((g) => g.items.length), hidden: total - shown };
}

// Reparte en dos columnas sin cortar un organismo, equilibrando renglones.
function splitColumns<T extends number>(lines: T[]): T[][] {
  const total = lines.reduce((a, b) => a + b, 0);
  const left: T[] = [];
  let acc = 0;
  for (const n of lines) {
    if (acc + n / 2 > total / 2 && left.length) break;
    left.push(n);
    acc += n;
  }
  return [left, lines.slice(left.length)];
}

function splitItems(items: string[][]): [string[][], string[][]] {
  const counts = items.map((l) => l.length);
  const [left] = splitColumns(counts);
  return [items.slice(0, left.length), items.slice(left.length)];
}

const Item: React.FC<{ lines: string[]; size: number; ink: string }> = ({ lines, size, ink }) => (
  <div style={{ display: "flex", gap: size * 0.45, marginBottom: size * ITEM_GAP }}>
    <span style={{ width: size * 0.32, height: size * 0.32, backgroundColor: C.red, marginTop: size * 0.38, flexShrink: 0 }} />
    <div style={{ fontFamily: `"${V2_FONT_SANS}"`, fontWeight: 700, fontStretch: "semi-condensed", fontSize: size, lineHeight: 1.12, color: ink }}>
      {lines.map((l, i) => (
        <div key={i}>{l}</div>
      ))}
    </div>
  </div>
);

// Titular + concepto + organismos. Ocupa `width` × `height` desde arriba.
export const PaymentsBlock: React.FC<{ headline: string; subhead: string; groups: Group[]; width: number; height: number; ink: string; mute: string }> = ({
  headline,
  subhead,
  groups,
  width,
  height,
  ink,
  mute,
}) => {
  const head = fit({ text: headline, maxWidth: width, maxHeight: 210, min: 60, max: 104, weight: 900, lh: 1.0, stretch: "condensed", maxLines: 2 });
  const listTop = head.height + 96;
  const layout = layoutGroups(groups, width, height - listTop);
  return (
    <div style={{ width, height, display: "flex", flexDirection: "column" }}>
      <div style={{ ...display(head.fontSize, ink, 900, "condensed"), lineHeight: `${head.lineHeight}px` }}>
        {head.lines.map((l, i) => (
          <div key={i}>{l}</div>
        ))}
      </div>
      <div style={{ ...serif(40, mute), marginTop: 14, marginBottom: 42 }}>{subhead}</div>
      {layout.groups.map((g, gi) => {
        const columns = layout.columns === 2 ? splitItems(g.items) : [g.items];
        return (
          <div key={gi} style={{ marginBottom: layout.size * GROUP_GAP }}>
            {g.title ? <div style={{ ...caps(Math.round(layout.size * 0.78), C.red, 900, 0.14), marginBottom: layout.size * 0.6 }}>{g.title}</div> : null}
            <div style={{ display: "flex", gap: 48 }}>
              {columns.map((col, ci) => (
                <div key={ci} style={{ flex: 1, display: "flex", flexDirection: "column" }}>
                  {col.map((lines, i) => (
                    <Item key={i} lines={lines} size={layout.size} ink={ink} />
                  ))}
                </div>
              ))}
            </div>
          </div>
        );
      })}
      {layout.hidden > 0 ? <div style={serif(30, mute)}>y {layout.hidden} organismos más</div> : null}
    </div>
  );
};

// Magnitud grande + titular + hora, epicentro, profundidad y localidades.
export const QuakeBlock: React.FC<{
  magnitude: string;
  headline: string;
  timeLabel: string;
  epicenter: string;
  depth: string;
  felt: z.infer<typeof FeltPlace>[];
  width: number;
  compact?: boolean;
}> = ({ magnitude, headline, timeLabel, epicenter, depth, felt, width, compact }) => {
  const epi = fit({ text: epicenter, maxWidth: width, maxHeight: compact ? 100 : 150, min: 26, max: 36, weight: 500, lh: 1.3, italic: true, family: V2_FONT_SERIF, maxLines: compact ? 2 : 3 });
  const rows = felt.slice(0, compact ? 4 : 6);
  return (
    <div style={{ width, display: "flex", flexDirection: "column", gap: compact ? 26 : 36 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 34 }}>
        <span style={{ ...display(compact ? 220 : 280, C.white, 900, "condensed"), lineHeight: 0.82 }}>{magnitude}</span>
        <div style={{ display: "flex", flexDirection: "column", gap: 14, paddingBottom: 10 }}>
          <span style={caps(26, "#F2A900", 900, 0.16)}>Magnitud</span>
          <span style={caps(24, rgba(C.white, 0.7), 700, 0.12)}>{timeLabel}</span>
        </div>
      </div>
      <div style={{ ...display(compact ? 70 : 84, C.white, 900, "condensed"), lineHeight: 1.0 }}>{headline}</div>
      <div style={{ borderLeft: "6px solid #F2A900", paddingLeft: 26, display: "flex", flexDirection: "column", gap: 12 }}>
        <span style={caps(21, rgba(C.white, 0.6), 800, 0.16)}>Epicentro</span>
        <div style={{ ...serif(epi.fontSize, rgba(C.white, 0.9)), lineHeight: `${epi.lineHeight}px` }}>
          {epi.lines.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
        {depth ? <span style={caps(22, rgba(C.white, 0.75), 700, 0.1)}>{depth}</span> : null}
      </div>
      {rows.length ? (
        <div style={{ display: "flex", flexDirection: "column" }}>
          <span style={{ ...caps(21, rgba(C.white, 0.6), 800, 0.16), marginBottom: 12 }}>Se sintió en</span>
          {rows.map((f, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: compact ? "14px 0" : "18px 0", borderTop: `2px solid ${rgba(C.white, 0.14)}` }}>
              <span style={display(compact ? 36 : 42, C.white, 800)}>{f.place}</span>
              <span style={{ ...caps(22, C.ink, 900, 0.06), backgroundColor: "#F2A900", padding: "10px 16px" }}>Intensidad {f.intensity}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
};
