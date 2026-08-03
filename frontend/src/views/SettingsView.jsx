import React, { useState } from 'react'
import { motion } from 'framer-motion'
import {
  Type, AlignJustify, MousePointer2, Keyboard, Volume2, BookOpen,
  Link2, Heading, MousePointerClick, Maximize2, Eye, Moon, Sun, Droplet, Droplets,
  Contrast, Palette, RotateCcw, Minus, Plus, ChevronDown, ChevronUp,
} from 'lucide-react'
import { useAccessibility } from '../hooks/useAccessibility'
import { useLanguage } from '../hooks/useLanguage'

function CategorySection({ icon, title, description, children }) {
  const { t } = useLanguage()
  const [open, setOpen] = useState(true)
  return (
    <div className="stat-card" style={{ marginBottom: '20px' }}>
      <div
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}
        onClick={() => setOpen(o => !o)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: 32, height: 32, borderRadius: '8px', flexShrink: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'rgba(246, 192, 38, 0.14)', color: 'var(--primary-color)',
          }}>
            {icon}
          </div>
          <div>
            <h3 style={{ fontSize: '15px', fontWeight: 700 }}>{title}</h3>
            {description && <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{description}</p>}
          </div>
        </div>
        <button
          aria-label={open ? t('common.collapse') : t('common.expand')}
          style={{
            width: 28, height: 28, borderRadius: '6px', cursor: 'pointer', flexShrink: 0,
            border: '1px solid var(--border-color)', background: 'var(--bg-card)',
            color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      </div>
      {open && <div style={{ marginTop: '18px' }}>{children}</div>}
    </div>
  )
}

function Tile({ icon, label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '10px',
        padding: '18px 10px', borderRadius: '10px', cursor: 'pointer', textAlign: 'center',
        border: active ? '2px solid var(--primary-color)' : '1px solid var(--border-color)',
        background: active ? 'rgba(246, 192, 38, 0.12)' : 'var(--bg-card)',
        color: 'var(--text-main)',
      }}
    >
      {icon}
      <span style={{ fontSize: '12px', fontWeight: 600 }}>{label}</span>
    </button>
  )
}

function TileGrid({ children }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: '12px' }}>
      {children}
    </div>
  )
}

function LevelStepper({ icon, title, description, levels, value, onChange, onReset }) {
  const { t } = useLanguage()
  const index = Math.max(0, levels.findIndex(l => l.value === value))
  return (
    <div style={{ padding: '16px 0', borderBottom: '1px solid var(--border-color)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
        {icon}
        <div>
          <div style={{ fontSize: '14px', fontWeight: 600 }}>{title}</div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{description}</div>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <button
          onClick={() => onChange(levels[Math.max(0, index - 1)].value)}
          disabled={index === 0}
          style={{
            width: 30, height: 30, borderRadius: '50%', border: 'none', cursor: 'pointer',
            background: 'var(--primary-color)', color: '#0f172a', display: 'flex', alignItems: 'center', justifyContent: 'center',
            opacity: index === 0 ? 0.4 : 1, flexShrink: 0,
          }}
        >
          <Minus size={14} />
        </button>
        <div style={{ flex: 1, display: 'flex', gap: '4px' }}>
          {levels.map((l, i) => (
            <div key={l.value} style={{
              flex: 1, height: '8px', borderRadius: '4px',
              background: i <= index ? 'var(--primary-color)' : '#e2e8f0',
            }} />
          ))}
        </div>
        <button
          onClick={() => onChange(levels[Math.min(levels.length - 1, index + 1)].value)}
          disabled={index === levels.length - 1}
          style={{
            width: 30, height: 30, borderRadius: '50%', border: 'none', cursor: 'pointer',
            background: 'var(--primary-color)', color: '#0f172a', display: 'flex', alignItems: 'center', justifyContent: 'center',
            opacity: index === levels.length - 1 ? 0.4 : 1, flexShrink: 0,
          }}
        >
          <Plus size={14} />
        </button>
        <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', minWidth: '70px' }}>
          {levels[index].label}
        </span>
        <button
          onClick={onReset}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
        >
          <RotateCcw size={12} /> {t('common.reset')}
        </button>
      </div>
    </div>
  )
}

const getColorTabs = (t) => [
  { key: 'background', label: t('settings.colorTabBackgrounds') },
  { key: 'headings', label: t('settings.colorTabHeadings') },
  { key: 'contents', label: t('settings.colorTabContents') },
]

function CustomColorPanel() {
  const { t } = useLanguage()
  const { settings, updateCustomColor, resetCustomColors } = useAccessibility()
  const [activeTab, setActiveTab] = useState('background')
  const [hue, setHue] = useState(40)

  const applyHue = (h) => {
    setHue(h)
    updateCustomColor(activeTab, `hsl(${h}, 70%, 45%)`)
  }

  const currentSwatch = settings.customColors[activeTab]
  const colorTabs = getColorTabs(t)

  return (
    <div style={{ padding: '16px 0', borderTop: '1px solid var(--border-color)', marginTop: '8px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
        <Palette size={17} />
        <div>
          <div style={{ fontSize: '14px', fontWeight: 600 }}>{t('settings.customColor')}</div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('settings.customColorDesc')}</div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '14px' }}>
        {colorTabs.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              padding: '8px 16px', borderRadius: '999px', cursor: 'pointer', fontSize: '13px', fontWeight: 600,
              border: activeTab === tab.key ? 'none' : '1px solid var(--border-color)',
              background: activeTab === tab.key ? 'var(--primary-color)' : 'var(--bg-card)',
              color: activeTab === tab.key ? '#0f172a' : 'var(--text-muted)',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div style={{
          width: 24, height: 24, borderRadius: '50%', flexShrink: 0,
          background: currentSwatch || '#e2e8f0', border: '1px solid var(--border-color)',
        }} />
        <input
          type="range"
          min="0"
          max="360"
          value={hue}
          onChange={e => applyHue(Number(e.target.value))}
          style={{
            flex: 1, height: '10px', borderRadius: '999px', appearance: 'none',
            background: 'linear-gradient(to right, red, yellow, lime, cyan, blue, magenta, red)',
          }}
        />
        <button
          onClick={resetCustomColors}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px', whiteSpace: 'nowrap' }}
        >
          <RotateCcw size={12} /> {t('settings.resetColors')}
        </button>
      </div>
    </div>
  )
}

export function SettingsView() {
  const { t } = useLanguage()
  const { settings, updateSetting, resetSettings } = useAccessibility()

  const colorFilterValue = (v) => settings.colorFilter === v
  const toggleColorFilter = (v) => updateSetting('colorFilter', settings.colorFilter === v ? 'none' : v)

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
      <div className="header">
        <div className="header-title">
          <h1>{t('settings.title')}</h1>
          <p>{t('settings.subtitle')}</p>
        </div>
        <div className="header-actions">
          <button
            onClick={resetSettings}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              padding: '8px 14px', borderRadius: '8px',
              border: '1px solid var(--border-color)', background: 'var(--bg-card)',
              color: 'var(--text-muted)', fontSize: '13px', fontWeight: 600, cursor: 'pointer',
            }}
          >
            <RotateCcw size={14} />
            {t('settings.resetAll')}
          </button>
        </div>
      </div>

      <CategorySection icon={<Keyboard size={17} />} title={t('settings.navigation')} description={t('settings.navigationDesc')}>
        <TileGrid>
          <Tile
            icon={<Keyboard size={22} />}
            label={t('settings.keyboardNav')}
            active={settings.keyboardNav}
            onClick={() => updateSetting('keyboardNav', !settings.keyboardNav)}
          />
          <Tile
            icon={<Volume2 size={22} />}
            label={t('settings.textReader')}
            active={settings.textReader}
            onClick={() => updateSetting('textReader', !settings.textReader)}
          />
        </TileGrid>
      </CategorySection>

      <CategorySection icon={<Palette size={17} />} title={t('settings.colorAdjustment')} description={t('settings.colorAdjustmentDesc')}>
        <TileGrid>
          <Tile icon={<Eye size={22} />} label={t('settings.monochrome')} active={colorFilterValue('monochrome')} onClick={() => toggleColorFilter('monochrome')} />
          <Tile icon={<Moon size={22} />} label={t('settings.darkContrast')} active={colorFilterValue('dark-contrast')} onClick={() => toggleColorFilter('dark-contrast')} />
          <Tile icon={<Sun size={22} />} label={t('settings.brightContrast')} active={colorFilterValue('bright-contrast')} onClick={() => toggleColorFilter('bright-contrast')} />
          <Tile icon={<Droplet size={22} />} label={t('settings.lowSaturation')} active={colorFilterValue('low-saturation')} onClick={() => toggleColorFilter('low-saturation')} />
          <Tile icon={<Droplets size={22} />} label={t('settings.highSaturation')} active={colorFilterValue('high-saturation')} onClick={() => toggleColorFilter('high-saturation')} />
          <Tile icon={<Contrast size={22} />} label={t('settings.contrastMode')} active={colorFilterValue('contrast-mode')} onClick={() => toggleColorFilter('contrast-mode')} />
        </TileGrid>
        <CustomColorPanel />
      </CategorySection>

      <CategorySection icon={<Type size={17} />} title={t('settings.contentAdjustment')} description={t('settings.contentAdjustmentDesc')}>
        <LevelStepper
          icon={<Type size={17} />}
          title={t('settings.textSize')}
          description={t('settings.textSizeDesc')}
          levels={[{ value: 'normal', label: t('settings.levelNormal') }, { value: 'large', label: t('settings.levelLarge') }, { value: 'larger', label: t('settings.levelLarger') }]}
          value={settings.fontSize}
          onChange={v => updateSetting('fontSize', v)}
          onReset={() => updateSetting('fontSize', 'normal')}
        />
        <LevelStepper
          icon={<AlignJustify size={17} />}
          title={t('settings.textSpacing')}
          description={t('settings.textSpacingDesc')}
          levels={[{ value: 'normal', label: t('settings.levelNormal') }, { value: 'increased', label: t('settings.levelIncreased') }]}
          value={settings.spacing}
          onChange={v => updateSetting('spacing', v)}
          onReset={() => updateSetting('spacing', 'normal')}
        />
        <LevelStepper
          icon={<MousePointer2 size={17} />}
          title={t('settings.cursorSize')}
          description={t('settings.cursorSizeDesc')}
          levels={[{ value: 'normal', label: t('settings.levelNormal') }, { value: 'large', label: t('settings.levelLarge') }]}
          value={settings.cursorSize}
          onChange={v => updateSetting('cursorSize', v)}
          onReset={() => updateSetting('cursorSize', 'normal')}
        />

        <div style={{ marginTop: '16px' }}>
          <TileGrid>
            <Tile icon={<BookOpen size={22} />} label={t('settings.readableFont')} active={settings.dyslexiaFont} onClick={() => updateSetting('dyslexiaFont', !settings.dyslexiaFont)} />
            <Tile icon={<Link2 size={22} />} label={t('settings.highlightLinks')} active={settings.highlightLinks} onClick={() => updateSetting('highlightLinks', !settings.highlightLinks)} />
            <Tile icon={<Heading size={22} />} label={t('settings.highlightHeaders')} active={settings.highlightHeaders} onClick={() => updateSetting('highlightHeaders', !settings.highlightHeaders)} />
            <Tile icon={<MousePointerClick size={22} />} label={t('settings.highlightElements')} active={settings.highlightElements} onClick={() => updateSetting('highlightElements', !settings.highlightElements)} />
            <Tile icon={<Maximize2 size={22} />} label={t('settings.enlargeButtons')} active={settings.enlargeButtons} onClick={() => updateSetting('enlargeButtons', !settings.enlargeButtons)} />
          </TileGrid>
        </div>
      </CategorySection>
    </motion.div>
  )
}
