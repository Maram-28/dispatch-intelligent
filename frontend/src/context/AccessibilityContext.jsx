import React, { useEffect, useState } from 'react'
import { AccessibilityContext } from './accessibilityContextObject'
import { useTextReader } from '../hooks/useTextReader'

const STORAGE_KEY = 'smartdispatch_accessibility'

const DEFAULT_SETTINGS = {
  fontSize: 'normal',        // 'normal' | 'large' | 'larger'
  spacing: 'normal',         // 'normal' | 'increased'
  cursorSize: 'normal',      // 'normal' | 'large'
  colorFilter: 'none',       // 'none' | 'monochrome' | 'low-saturation' | 'high-saturation' | 'dark-contrast' | 'bright-contrast' | 'contrast-mode'
  customColors: { background: null, headings: null, contents: null },
  highlightLinks: false,
  highlightHeaders: false,
  highlightElements: false,
  enlargeButtons: false,
  keyboardNav: false,
  dyslexiaFont: false,
  textReader: false,
}

function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_SETTINGS
    const parsed = JSON.parse(raw)
    return { ...DEFAULT_SETTINGS, ...parsed, customColors: { ...DEFAULT_SETTINGS.customColors, ...parsed.customColors } }
  } catch {
    return DEFAULT_SETTINGS
  }
}

// Le sélecteur de couleur produit une teinte claire adaptée au contenu
// (hsl(hue, 70%, 45%)) — on en dérive une variante sombre pour la sidebar
// (toujours foncée par défaut) à partir de la même teinte, pour qu'elle
// suive vraiment "Couleur personnalisée > Fonds" au lieu de rester figée.
function deriveSidebarShade(hslColor) {
  const match = /^hsl\((\d+)/.exec(hslColor || '')
  if (!match) return null
  return `hsl(${match[1]}, 45%, 12%)`
}

function applyToDocument(settings) {
  const root = document.documentElement
  root.setAttribute('data-font-size', settings.fontSize)
  root.setAttribute('data-spacing', settings.spacing)
  root.setAttribute('data-cursor-size', settings.cursorSize)
  root.setAttribute('data-color-filter', settings.colorFilter)
  root.setAttribute('data-highlight-links', String(settings.highlightLinks))
  root.setAttribute('data-highlight-headers', String(settings.highlightHeaders))
  root.setAttribute('data-highlight-elements', String(settings.highlightElements))
  root.setAttribute('data-enlarge-buttons', String(settings.enlargeButtons))
  root.setAttribute('data-dyslexia-font', String(settings.dyslexiaFont))

  const setOrClear = (prop, value) => {
    if (value) root.style.setProperty(prop, value)
    else root.style.removeProperty(prop)
  }
  setOrClear('--custom-bg', settings.customColors.background)
  setOrClear('--custom-bg-sidebar', deriveSidebarShade(settings.customColors.background))
  setOrClear('--custom-headings', settings.customColors.headings)
  setOrClear('--custom-contents', settings.customColors.contents)
}

export function AccessibilityProvider({ children }) {
  const [settings, setSettings] = useState(loadSettings)

  useEffect(() => {
    applyToDocument(settings)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  }, [settings])

  useTextReader(settings.textReader)

  const updateSetting = (key, value) => {
    setSettings(prev => ({ ...prev, [key]: value }))
  }

  const updateCustomColor = (target, value) => {
    setSettings(prev => ({ ...prev, customColors: { ...prev.customColors, [target]: value } }))
  }

  const resetCustomColors = () => {
    setSettings(prev => ({ ...prev, customColors: { ...DEFAULT_SETTINGS.customColors } }))
  }

  const resetSettings = () => setSettings(DEFAULT_SETTINGS)

  return (
    <AccessibilityContext.Provider value={{ settings, updateSetting, updateCustomColor, resetCustomColors, resetSettings }}>
      {children}
    </AccessibilityContext.Provider>
  )
}
