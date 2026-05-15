/* Minimal tracking bootstrap */
(function(){
  var config = window.siteConfig || {};
  function initTracking(consented){
    var tools = (config.tracking_tools || {});
    var consentMode = (config.consent && config.consent.mode) || 'opt-in';

    if (tools.google_analytics && tools.google_analytics.enabled && (consented || consentMode === 'opt-out')) {
      // Simulate GA load
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event: 'ga_init', id: (tools.google_analytics && tools.google_analytics.measurement_id) });
    }

    if (tools.facebook_pixel && tools.facebook_pixel.enabled && (consented || consentMode === 'opt-out')) {
      // Simulate FB Pixel load
      window.fbq = window.fbq || function(){};
      try {
        fbq('init', tools.facebook_pixel.pixel_id);
        fbq('track', 'PageView');
      } catch(e) {}
    }

    if (tools.hotjar && tools.hotjar.enabled && consented) {
      // Simulate Hotjar load only when consented
      window.hj = window.hj || function(){};
      hj('trigger', 'init');
    }
  }

  document.addEventListener('DOMContentLoaded', function(){
    var userConsented = false; // Default before any user action
    initTracking(userConsented);
  });
})();
