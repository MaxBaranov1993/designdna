(function (global) {
  "use strict";

  const groups = [
    { label: "Sans", fonts: [
      "Inter", "Roboto", "Open Sans", "Lato", "Montserrat", "Poppins", "Nunito", "Raleway",
      "Source Sans 3", "Work Sans", "DM Sans", "Manrope", "Sora", "Space Grotesk",
      "Plus Jakarta Sans", "Urbanist", "Outfit", "Rubik", "Mulish", "Noto Sans",
      "Noto Sans Display", "Noto Sans JP", "Noto Sans KR", "Noto Sans SC", "Noto Sans Thai",
      "PT Sans", "Ubuntu", "Fira Sans", "Barlow", "Karla", "Cabin", "Hind", "Heebo",
      "IBM Plex Sans", "Alegreya Sans", "Exo 2", "Josefin Sans", "Quicksand", "Titillium Web"
    ]},
    { label: "Serif", fonts: [
      "Merriweather", "Playfair Display", "Lora", "Libre Baskerville", "Cormorant Garamond",
      "EB Garamond", "Crimson Text", "Bitter", "Source Serif 4", "Noto Serif",
      "Noto Serif Display", "PT Serif", "Alegreya", "Spectral", "Fraunces",
      "Prata", "Libre Bodoni", "DM Serif Display", "Vollkorn", "Cardo"
    ]},
    { label: "Mono", fonts: [
      "Roboto Mono", "Source Code Pro", "IBM Plex Mono", "JetBrains Mono", "Fira Code",
      "Fira Mono", "Space Mono", "DM Mono", "Inconsolata", "Ubuntu Mono",
      "Noto Sans Mono", "Red Hat Mono", "Azeret Mono"
    ]},
    { label: "Display", fonts: [
      "Bebas Neue", "Oswald", "Anton", "Archivo Black", "League Spartan", "Bungee",
      "Righteous", "Cinzel", "Abril Fatface", "Alfa Slab One", "Bodoni Moda",
      "Unbounded", "Russo One", "Teko", "Chakra Petch", "Orbitron", "Michroma",
      "Syne", "Clash Display", "Cormorant Infant"
    ]},
    { label: "Handwriting", fonts: [
      "Pacifico", "Caveat", "Dancing Script", "Lobster", "Comforter", "Marck Script",
      "Bad Script", "Shadows Into Light", "Permanent Marker", "Indie Flower",
      "Amatic SC", "Neucha"
    ]},
    { label: "System", provider: "system", fonts: [
      "Arial", "Helvetica", "Verdana", "Tahoma", "Trebuchet MS", "Georgia",
      "Times New Roman", "Courier New", "Segoe UI", "SF Pro Display", "SF Pro Text"
    ]}
  ];

  const googleFamilies = new Set(groups.filter(g => g.provider !== "system").flatMap(g => g.fonts));
  const systemFamilies = new Set(groups.filter(g => g.provider === "system").flatMap(g => g.fonts));
  const families = groups.flatMap(g => g.fonts);

  global.DesignAIFontCatalog = {
    groups,
    families,
    googleFamilies,
    systemFamilies,
    isGoogleFamily(name) {
      return googleFamilies.has(String(name || "").trim());
    },
    isSystemFamily(name) {
      return systemFamilies.has(String(name || "").trim());
    }
  };
})(window);
