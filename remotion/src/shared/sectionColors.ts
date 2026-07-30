import { AZUL, BORDO, ROJO } from "../constants";

// Espeja SECTION_COLORS de layout/image_generator.py (Python), pero con la
// paleta oficial de la Fase 4 (rojo/bordó/azul, sin dorado).
const SECTION_COLORS: Record<string, string> = {
  politica: AZUL,
  policiales: ROJO,
  interior: AZUL,
  sociedad: AZUL,
  economia: AZUL,
  salud: AZUL,
  educacion: AZUL,
  deportes: AZUL,
  cultura: BORDO,
  espectaculos: BORDO,
  locales: ROJO,
};

export function section_color_token(seccion: string): string {
  return SECTION_COLORS[(seccion || "").toLowerCase().trim()] || ROJO;
}
