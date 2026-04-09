import re

with open("../frontend/src/pages/Settings.jsx", "r") as f:
    rules_page = f.read()

# I will just write a whole new file here since I know exact contents of both
new_file = """import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  FormControlLabel,
  Link,
  Stack,
  Switch,
  Tab,
  Tabs,
  Typography,
} from '@mui/material'
import { Link as RouterLink, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMemo, useState } from 'react'
import PageHeader from '../components/PageHeader'
import {
  dataCardWidthSx,
  layoutMajorDividerSx,
  layoutSectionSpacing,
  pageStackWidthSx,
} from '../utils/responsiveTable'
import useAppMeta from '../contexts/useAppMeta'
import { reprocessAllEmailsOffline } from '../services/financeApi'
import AppConfigSection from '../components/AppConfigSection'
import ClassificationsSection from '../components/rules/ClassificationsSection'
import ParsersSection from '../components/rules/ParsersSection'
import ExclusionRulesSection from '../components/rules/ExclusionRulesSection'

const META_ROWS = [
  { key: 'app_version', label: 'App version' },
  { key: 'mail_user_email', label: 'Gmail account' },
  { key: 'is_healthy', label: 'API healthy', format: 'bool' },
  { key: 'is_initialized', label: 'Initialized', format: 'bool' },
  { key: 'is_mail_connectivity_working', label: 'Mail connectivity', format: 'bool' },
  { key: 'docs_url', label: 'API docs', format: 'url' },
  { key: 'openapi_url', label: 'OpenAPI JSON', format: 'url' },
  { key: 'redoc_url', label: 'ReDoc', format: 'url' },
]

function formatMetaValue(meta, { key, format: fmt }) {
  const raw = meta?.[key]
  if (raw === null || raw === undefined || raw === '') return null
  if (fmt === 'bool') {
    return (
      <Chip
        size="small"
        label={raw ? 'Yes' : 'No'}
        color={raw ? 'success' : 'default'}
        variant={raw ? 'filled' : 'outlined'}
        sx={{ height: 22 }}
      />
    )
  }
  if (fmt === 'url' && typeof raw === 'string') {
    return (
      <Link href={raw} target="_blank" rel="noopener noreferrer" variant="body2">
        {raw}
      </Link>
    )
  }
  return String(raw)
}

function rulesQuerySuffix(searchParams) {
  const sp = new URLSearchParams(searchParams)
  sp.delete('tab')
  const qs = sp.toString()
  return qs ? `?${qs}` : ''
}

function ApiTab() {
  const meta = useAppMeta()
  const [reprocessState, setReprocessState] = useState({
    status: 'idle',
    message: '',
  })

  const onReprocessAll = async () => {
    setReprocessState({ status: 'loading', message: '' })
    try {
      await reprocessAllEmailsOffline()
      setReprocessState({
        status: 'success',
        message: 'Reprocess started for all cached emails.',
      })
    } catch (e) {
      const msg = e?.message ?? 'Request failed'
      setReprocessState({ status: 'error', message: msg })
    }
  }

  return (
    <CardContent>
      {meta ? (
        <Stack
          component="dl"
          spacing={{ xs: 0.75, md: 1.25 }}
          sx={{ m: 0 }}
        >
          {META_ROWS.map((row) => {
            const value = formatMetaValue(meta, row)
            if (value == null) return null
            return (
              <Box
                key={row.key}
                sx={{
                  display: 'grid',
                  gridTemplateColumns: { xs: '1fr', sm: 'minmax(140px, 200px) 1fr' },
                  gap: { xs: 0.25, sm: 2 },
                  alignItems: 'center',
                }}
              >
                <Typography
                  component="dt"
                  variant="body2"
                  color="text.secondary"
                  sx={{ fontWeight: 500 }}
                >
                  {row.label}
                </Typography>
                <Box component="dd" sx={{ m: 0 }}>
                  {value}
                </Box>
              </Box>
            )
          })}
        </Stack>
      ) : (
        <Typography variant="body2" color="text.secondary">
          No metadata loaded.
        </Typography>
      )}
      <Divider sx={{ my: 2, ...layoutMajorDividerSx }} />
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
        <Button
          size="small"
          variant="contained"
          onClick={onReprocessAll}
          disabled={reprocessState.status === 'loading'}
        >
          Reprocess All Emails
        </Button>
      </Box>
      {reprocessState.message && (
        <Box sx={{ mt: 1 }}>
          <Alert
            severity={reprocessState.status === 'error' ? 'error' : 'success'}
          >
            {reprocessState.message}
          </Alert>
        </Box>
      )}
    </CardContent>
  )
}

export default function Settings() {
  const navigate = useNavigate()
  const location = useLocation()
  const params = useParams()
  const [searchParams] = useSearchParams()

  const classificationIdParam = params.classificationId
  const parserIdParam = params.parserId
  const exclusionRuleIdParam = params.exclusionRuleId

  const routeClassificationNew = classificationIdParam === 'new'
  const routeParserNew = parserIdParam === 'new'
  const routeExclusionNew = exclusionRuleIdParam === 'new'

  const routeClassificationId = useMemo(() => {
    if (routeClassificationNew) return null
    const n = Number(classificationIdParam)
    return Number.isFinite(n) ? n : null
  }, [classificationIdParam, routeClassificationNew])

  const routeParserId = useMemo(() => {
    if (routeParserNew) return null
    const n = Number(parserIdParam)
    return Number.isFinite(n) ? n : null
  }, [parserIdParam, routeParserNew])

  const routeExclusionId = useMemo(() => {
    if (routeExclusionNew) return null
    const n = Number(exclusionRuleIdParam)
    return Number.isFinite(n) ? n : null
  }, [exclusionRuleIdParam, routeExclusionNew])

  const isClassificationsPath = location.pathname.startsWith('/settings/classifications')
  const isParsersPath = location.pathname.startsWith('/settings/parsers')
  const isExclusionsPath = location.pathname.startsWith('/settings/exclusions')
  const isAppConfigPath = location.pathname.startsWith('/settings/app-config')
  const isSystemPath = location.pathname.startsWith('/settings/system')

  const tab = useMemo(() => {
    if (isClassificationsPath) return 0
    if (isParsersPath) return 1
    if (isExclusionsPath) return 2
    if (isAppConfigPath) return 3
    if (isSystemPath) return 4
    return 0
  }, [
    isClassificationsPath,
    isParsersPath,
    isExclusionsPath,
    isAppConfigPath,
    isSystemPath
  ])

  const [classificationsShowInactive, setClassificationsShowInactive] = useState(false)
  const [parsersShowInactive, setParsersShowInactive] = useState(false)
  const [exclusionsShowInactive, setExclusionsShowInactive] = useState(false)

  const showInactive =
    tab === 0 ? classificationsShowInactive : tab === 1 ? parsersShowInactive : exclusionsShowInactive
  const setShowInactive =
    tab === 0 ? setClassificationsShowInactive : tab === 1 ? setParsersShowInactive : setExclusionsShowInactive

  const triggerCreate = () => {
    const suffix = rulesQuerySuffix(searchParams)
    if (tab === 0) {
      navigate(`/settings/classifications/new${suffix}`)
    } else if (tab === 1) {
      navigate(`/settings/parsers/new${suffix}`)
    } else if (tab === 2) {
      navigate(`/settings/exclusions/new${suffix}`)
    }
  }

  const setTabAndUrl = (nextTab) => {
    const suffix = rulesQuerySuffix(searchParams)
    let path = '/settings/classifications'
    if (nextTab === 1) path = '/settings/parsers'
    if (nextTab === 2) path = '/settings/exclusions'
    if (nextTab === 3) path = '/settings/app-config'
    if (nextTab === 4) path = '/settings/system'
    navigate(`${path}${suffix}`)
  }

  const openClassificationById = (id) => {
    const suffix = rulesQuerySuffix(searchParams)
    navigate(`/settings/classifications/${id}${suffix}`)
  }

  const closeClassificationRoute = () => {
    const sp = new URLSearchParams()
    const ret = searchParams.get('returnTo')
    if (ret) sp.set('returnTo', ret)
    const qs = sp.toString()
    navigate(qs ? `/settings/classifications?${qs}` : '/settings/classifications')
  }

  const openParserById = (id) => {
    const suffix = rulesQuerySuffix(searchParams)
    navigate(`/settings/parsers/${id}${suffix}`)
  }

  const closeParserRoute = () => {
    const sp = new URLSearchParams()
    const ret = searchParams.get('returnTo')
    if (ret) sp.set('returnTo', ret)
    const qs = sp.toString()
    navigate(qs ? `/settings/parsers?${qs}` : '/settings/parsers')
  }

  const openExclusionById = (id) => {
    const suffix = rulesQuerySuffix(searchParams)
    navigate(`/settings/exclusions/${id}${suffix}`)
  }

  const closeExclusionRoute = () => {
    const sp = new URLSearchParams()
    const ret = searchParams.get('returnTo')
    if (ret) sp.set('returnTo', ret)
    const qs = sp.toString()
    navigate(qs ? `/settings/exclusions?${qs}` : '/settings/exclusions')
  }

  return (
    <Stack spacing={layoutSectionSpacing} sx={pageStackWidthSx}>
      <PageHeader
        title="Settings"
      />

      <Card variant="outlined" sx={dataCardWidthSx}>
        <Box
          sx={{
            px: 2,
            pt: 1,
            display: 'flex',
            alignItems: 'center',
            gap: layoutSectionSpacing,
            flexWrap: 'wrap',
            justifyContent: 'space-between',
          }}
        >
          <Tabs
            value={tab}
            onChange={(_, v) => setTabAndUrl(v)}
            variant="scrollable"
            sx={{ borderBottom: 1, borderColor: 'divider', width: '100%' }}
          >
            <Tab label="Classifications" />
            <Tab label="Parsers" />
            <Tab label="Exclusion Rules" />
            <Tab label="API Configuration" />
            <Tab label="API & System" />
          </Tabs>

          {tab < 3 && (
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
              <FormControlLabel
                control={
                  <Switch
                    size="small"
                    checked={showInactive}
                    onChange={(e) => setShowInactive(e.target.checked)}
                  />
                }
                label="Show Inactive"
                sx={{ m: 0, userSelect: 'none' }}
              />
              <Button size="small" variant="contained" onClick={triggerCreate}>
                Add
              </Button>
            </Stack>
          )}
        </Box>
        <Box sx={{ p: 2, pt: 1.5 }}>
          {tab === 0 ? (
            <ClassificationsSection
              showInactive={classificationsShowInactive}
              routeId={routeClassificationId}
              routeCreate={routeClassificationNew}
              onOpenRule={openClassificationById}
              onCloseRule={closeClassificationRoute}
            />
          ) : tab === 1 ? (
            <ParsersSection
               showInactive={parsersShowInactive}
               routeId={routeParserId}
               routeCreate={routeParserNew}
               onOpenRule={openParserById}
               onCloseRule={closeParserRoute}
            />
          ) : tab === 2 ? (
            <ExclusionRulesSection
              showInactive={exclusionsShowInactive}
              routeId={routeExclusionId}
              routeCreate={routeExclusionNew}
              onOpenRule={openExclusionById}
              onCloseRule={closeExclusionRoute}
            />
          ) : tab === 3 ? (
            <AppConfigSection />
          ) : (
            <ApiTab />
          )}
        </Box>
      </Card>
      
      {tab < 3 && (
        <Alert severity="info">
          Deleting rules deactivates them (rows are kept for auditing and ingest
          behavior).
        </Alert>
      )}
    </Stack>
  )
}
"""

with open("../frontend/src/pages/Settings.jsx", "w") as f:
    f.write(new_file)

