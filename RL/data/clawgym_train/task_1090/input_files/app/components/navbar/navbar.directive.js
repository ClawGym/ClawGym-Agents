(function() {
  'use strict';
  angular.module('demoApp').directive('navBar', function() {
    return {
      restrict: 'E',
      scope: {},
      templateUrl: 'app/templates/navbar.html'
    };
  });
})();
