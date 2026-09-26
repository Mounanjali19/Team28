import { Link, Navigate, Route, Routes } from "react-router-dom";
import { homeFor, useAuth } from "./hooks/useAuth";
import LenderLayout from "./layouts/LenderLayout";
import UserLayout from "./layouts/UserLayout";
import AdminHome from "./pages/admin/AdminHome";
import Analytics from "./pages/lender/Analytics";
import CandidateDetail from "./pages/lender/CandidateDetail";
import Candidates from "./pages/lender/Candidates";
import LenderDashboard from "./pages/lender/LenderDashboard";
import SentOffers from "./pages/lender/SentOffers";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Applications from "./pages/user/Applications";
import Dashboard from "./pages/user/Dashboard";
import Offers from "./pages/user/Offers";
import ProfilePage from "./pages/user/ProfilePage";
import Products from "./pages/user/Products";
import Report from "./pages/user/Report";
import ScoreDetails from "./pages/user/ScoreDetails";
import Target from "./pages/user/Target";
import WhatIf from "./pages/user/WhatIf";

function Home() {
  const { session } = useAuth();
  return <Navigate to={session ? homeFor(session) : "/login"} replace />;
}

function NotFound() {
  return (
    <div className="page">
      <h1>Page not found</h1>
      <p className="muted" style={{ margin: "8px 0 16px" }}>That address doesn't exist.</p>
      <Link className="btn" to="/">Go home</Link>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/app" element={<UserLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="score" element={<ScoreDetails />} />
        <Route path="products" element={<Products />} />
        <Route path="what-if" element={<WhatIf />} />
        <Route path="target" element={<Target />} />
        <Route path="offers" element={<Offers />} />
        <Route path="applications" element={<Applications />} />
        <Route path="report" element={<Report />} />
        <Route path="profile" element={<ProfilePage />} />
      </Route>
      <Route path="/lender" element={<LenderLayout role="lender" />}>
        <Route index element={<LenderDashboard />} />
        <Route path="candidates" element={<Candidates base="/lender" />} />
        <Route path="candidates/:id" element={<CandidateDetail base="/lender" />} />
        <Route path="offers" element={<SentOffers />} />
        <Route path="analytics" element={<Analytics />} />
      </Route>
      <Route path="/admin" element={<LenderLayout role="admin" />}>
        <Route index element={<AdminHome />} />
        <Route path="candidates" element={<Candidates base="/admin" />} />
        <Route path="candidates/:id" element={<CandidateDetail base="/admin" />} />
        <Route path="analytics" element={<Analytics />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
