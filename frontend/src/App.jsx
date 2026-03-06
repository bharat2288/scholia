import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Library from './components/Library/Library'
import Reader from './components/Reader/Reader'
import Processor from './components/Processor/Processor'
import NetworkVolume from './components/Processor/NetworkVolume'
import Knowledge from './components/Knowledge/Knowledge'
import Gluon from './components/Gluon/Gluon'
import SectionEditor from './components/Editor/SectionEditor'
import Research from './components/Research/Research'
import MobileNavBar from './components/common/MobileNavBar'
import EvalDashboard from './components/Eval/EvalDashboard'

/**
 * Scholia App
 * ===========
 * Local-first research knowledge system.
 *
 * Routes:
 * - / : Library view (all documents)
 * - /read/:id : Reader view (document reading interface)
 * - /edit/:id : Section editor (fix OCR errors in extracted text)
 * - /processor : PDF processor (upload and extract)
 * - /processor/volume : Network Volume browser (RunPod storage)
 * - /knowledge : Knowledge view (all notes, tags, search)
 * - /gluon/:id : Gluon page (single knowledge unit with connections)
 * - /research : Research sessions with RLM chat
 */

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Library />} />
        <Route path="/read/:id" element={<Reader />} />
        <Route path="/edit/:id" element={<SectionEditor />} />
        <Route path="/processor" element={<Processor />} />
        <Route path="/processor/volume" element={<NetworkVolume />} />
        <Route path="/knowledge" element={<Knowledge />} />
        <Route path="/gluon/:id" element={<Gluon />} />
        <Route path="/research" element={<Research />} />
        <Route path="/eval" element={<EvalDashboard />} />
      </Routes>
      <MobileNavBar />
    </BrowserRouter>
  )
}

export default App
